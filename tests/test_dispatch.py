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
from tests.conftest import make_user, make_wallet


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

    async def test_catat_step_confirms_then_sends_new_prompt(self, app_dispatcher, session_factory,
                                                             monkeypatch):
        """UX multi-step: pilihan user di-edit ke prompt LAMA (konfirmasi),
        prompt langkah berikutnya dikirim sebagai pesan BARU — bukan edit."""
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/catat")))
        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="tx:t:expense",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))

        edits = api_calls(EditMessageText)
        sent = api_calls(SendMessage)
        # konfirmasi pilihan di prompt lama
        assert any("Anda memilih: 💸 Pengeluaran" in (m.text or "") for m in edits)
        # prompt jumlah sebagai pesan BARU (bukan edit prompt lama)
        assert any("Masukkan jumlah pengeluaran" in (m.text or "") for m in sent)

    async def test_catat_amount_echoed_in_prompt(self, app_dispatcher, session_factory,
                                                 monkeypatch):
        """Input teks jumlah ditempel di prompt lama, lalu prompt wallet pesan baru."""
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/catat")))
        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="tx:t:expense",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))
        await dp.feed_update(bot, Update(update_id=3, message=make_msg(123, 123, "25000")))

        edits = api_calls(EditMessageText)
        sent = api_calls(SendMessage)
        assert any("💵 Rp 25.000" in (m.text or "") for m in edits)  # jumlah di-echo ke prompt lama
        assert any("Pilih wallet" in (m.text or "") for m in sent)  # prompt wallet pesan baru

    async def test_toggle_setting_updates_in_place(self, app_dispatcher, session_factory,
                                                   monkeypatch):
        """Toggle (set:tins) = update pesan di tempat — tidak kirim pesan baru."""
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/pengaturan")))
        sent_before = len(api_calls(SendMessage))
        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="set:tins",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))

        assert len(api_calls(SendMessage)) == sent_before  # toggle TIDAK kirim pesan baru
        edits = api_calls(EditMessageText)
        assert any("Insight AI bulanan" in (m.text or "") for m in edits)  # info di-update di tempat

    async def test_admin_input_refreshes_panel_in_place(self, app_dispatcher, session_factory,
                                                        monkeypatch):
        """Input admin (transaksional): prompt pesan baru + konfirmasi;
        panel Konfigurasi AI di-refresh DI TEMPAT (bukan dikirim ulang)."""
        from app.config import settings as app_settings

        monkeypatch.setattr(app_settings, "admin_ids", "123")
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/admin")))
        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="adm:setmodel",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))
        await dp.feed_update(bot, Update(update_id=3, message=make_msg(123, 123, "gpt-4o-mini")))

        edits = api_calls(EditMessageText)
        sent = api_calls(SendMessage)
        # konfirmasi input di prompt
        assert any("🧠 gpt-4o-mini" in (m.text or "") for m in edits)
        # panel info di-refresh di tempat dengan nilai baru
        assert any("Model: gpt-4o-mini" in (m.text or "") for m in edits)
        # panel TIDAK dikirim ulang sebagai pesan baru
        assert not any("Konfigurasi AI" in (m.text or "") for m in sent)

    async def test_admin_user_detail_buttons(self, app_dispatcher, session_factory, monkeypatch):
        """Regression: detail user admin — ikb() menerima tuple, bukan objek tombol."""
        from app.config import settings as app_settings

        monkeypatch.setattr(app_settings, "admin_ids", "123")
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            target = await make_user(s, tg_id=555)
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/admin")))
        cb_list = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="adm:users:0",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb_list))
        cb_detail = CallbackQuery(
            id="2",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data=f"adm:user:{target.id}",
        )
        await dp.feed_update(bot, Update(update_id=3, callback_query=cb_detail))

        edits = api_calls(EditMessageText)
        assert any("👤" in (m.text or "") for m in edits)  # detail user dirender tanpa ValueError

    async def test_budget_menu_with_existing_budget(self, app_dispatcher, session_factory,
                                                    monkeypatch):
        """Regression: menu /budget dengan budget terdaftar — tombol via ikb(rows)."""
        from decimal import Decimal

        from app.db.models import Budget

        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            s.add(Budget(user_id=u.id, category_id=None, wallet_id=None,
                         period_type="monthly", amount=Decimal("100000")))
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/budget")))

        sent = api_calls(SendMessage)
        assert any("Budget" in (m.text or "") for m in sent)  # menu dirender tanpa ValueError

    async def test_admin_broadcast_button_starts_flow(self, app_dispatcher, session_factory,
                                                      monkeypatch):
        """Regression: tombol 📢 Broadcast di panel admin memulai flow broadcast —
        tidak jatuh ke catch-all 'tombol sudah tidak berlaku'."""
        from app.config import settings as app_settings

        monkeypatch.setattr(app_settings, "admin_ids", "123")
        dp, _ = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/admin")))
        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="adm:broadcast",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))

        sent = api_calls(SendMessage)
        assert any("Kirim teks broadcast" in (m.text or "") for m in sent)

    async def test_quick_add_ai_date_yesterday(self, app_dispatcher, session_factory, monkeypatch):
        """AI menyebut 'kemarin' → kartu menampilkan tanggal kemarin,
        simpan transaksi memakai tanggal itu (bukan hari ini)."""
        from datetime import timedelta

        from sqlalchemy import select

        from app.ai import client as ai_client
        from app.db.models import Transaction
        from app.utils.format import today_local

        yesterday = (today_local() - timedelta(days=1)).isoformat()

        async def fake_complete_json(session, messages, *, temperature=0.0):
            return {"action": "transaction", "type": "expense", "amount": 50000,
                    "category_guess": "Makan & Minum", "wallet_guess": "",
                    "note": "2 kopi kenangan", "date": yesterday, "confidence": "high"}

        monkeypatch.setattr(ai_client, "complete_json", fake_complete_json)

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        # storage dishare antar test — pastikan chat ini bebas FSM sisa
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(update_id=1,
                                         message=make_msg(123, 123, "kopi kenangan 2 50000 kemarin")))

        sent = api_calls(SendMessage)
        card = next(m for m in sent if "Transaksi Terdeteksi" in (m.text or ""))
        assert "Tanggal:" in card.text
        assert "Hari ini" not in card.text  # tanggal kemarin, bukan hari ini

        cb = CallbackQuery(
            id="1",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="qa:save",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))

        async with session_factory() as s:
            txs = (await s.execute(select(Transaction))).scalars().all()
        assert len(txs) == 1
        assert txs[0].occurred_at.isoformat() == yesterday
