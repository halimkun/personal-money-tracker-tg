"""Test dispatch end-to-end: Update mentah → middleware → handler.

Regression: middleware yang diregistrasi di dp.update menerima objek `Update`
mentah (bukan Message/CallbackQuery). Injeksi user & state-locking wajib
mengekstrak event aslinya lewat `Update.event` — bug di sini membuat semua
handler berparameter `user` crash dengan TypeError.

Semua panggilan API Telegram di-mock di `Bot.__call__` — aiogram 3.x memakai
pola `bot(method)` (message.answer, edit_or_send, dst.), bukan `bot.send_message`.
"""

from datetime import datetime
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TgUser

from app.handlers.states import QuickAddStates, WalletStates
from tests.conftest import make_user


async def make_bot(monkeypatch) -> Bot:
    bot = Bot(token="1:TEST")
    out = Message(message_id=99, date=datetime(2026, 8, 16), chat=Chat(id=1, type="private"))
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=out))
    monkeypatch.setattr(Bot, "get_me", AsyncMock(return_value=TgUser(id=42, is_bot=True, first_name="MoneyBot")))
    await bot.me()  # inisialisasi bot.id — dipakai FSM middleware (StorageKey)
    return bot


def api_calls(method_type) -> list:
    """Kumpulkan method object jenis tertentu dari semua panggilan API bot."""
    found = []
    for call in Bot.__call__.call_args_list:
        for arg in call.args:
            if isinstance(arg, method_type):
                found.append(arg)
    return found


def make_msg(chat_id: int, tg_id: int, text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime(2026, 8, 16),
        chat=Chat(id=chat_id, type="private"),
        from_user=TgUser(id=tg_id, is_bot=False, first_name="Tester"),
        text=text,
    )


class TestDispatch:
    async def test_command_gets_user_injected(self, app_dispatcher, session_factory, monkeypatch):
        """/wallet dari user terdaftar harus sampai ke handler (user ter-inject)."""
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/wallet")))

        sent = api_calls(SendMessage)
        assert any("Wallet Saya" in (m.text or "") for m in sent)  # menu dirender, tanpa TypeError

    async def test_unregistered_user_prompted(self, app_dispatcher, session_factory, monkeypatch):
        """User belum terdaftar diarahkan ke /start — quick-add AI tidak dipanggil."""
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(999, 999, "halo")))

        sent = api_calls(SendMessage)
        assert any("/start" in (m.text or "") for m in sent)

    async def test_locked_state_blocks_random_text(self, app_dispatcher, session_factory, monkeypatch):
        """FSM aktif + teks acak → ditolak state locking, tidak bocor ke quick-add."""
        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.set_state(QuickAddStates.awaiting_confirmation)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "beli kopi 20rb")))

        sent = api_calls(SendMessage)
        assert any("konfirmasi" in (m.text or "") for m in sent)  # pesan locked, bukan quick-add
        await ctx.clear()

    async def test_cancel_exempt_while_locked(self, app_dispatcher, session_factory, monkeypatch):
        """/cancel selalu lolos meski user locked (PRD §7b)."""
        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.set_state(WalletStates.entering_name)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/cancel")))

        assert await ctx.get_state() is None  # state dibersihkan handler /cancel

    async def test_callback_gets_user_injected(self, app_dispatcher, session_factory, monkeypatch):
        """Callback query lolos locking dan tetap mendapat user (wl:back)."""
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)
        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="wl:back",
        )

        await dp.feed_update(bot, Update(update_id=1, callback_query=cb))

        assert any(m.text for m in api_calls(EditMessageText))  # menu wallet dirender ulang
