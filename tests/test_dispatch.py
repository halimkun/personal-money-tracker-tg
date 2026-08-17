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

    async def test_quick_add_ai_old_receipt_date(self, app_dispatcher, session_factory, monkeypatch):
        """AI membaca tanggal struk lama (2024) → kartu & DB memakai tanggal itu,
        bukan 'Hari ini' (clamp tidak membuang tanggal struk lama)."""
        from sqlalchemy import select

        from app.ai import client as ai_client
        from app.db.models import Transaction

        async def fake_complete_json(session, messages, *, temperature=0.0):
            return {"action": "transaction", "type": "expense", "amount": 50000,
                    "category_guess": "Makan & Minum", "wallet_guess": "",
                    "note": "2 kopi kenangan", "date": "2024-06-20", "confidence": "high"}

        monkeypatch.setattr(ai_client, "complete_json", fake_complete_json)

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(update_id=1,
                                         message=make_msg(123, 123, "kopi kenangan 2 50000")))
        # jalur teks & foto struk sama-sama lewat _handle_result + _clamp_date
        sent = api_calls(SendMessage)
        card = next(m for m in sent if "Transaksi Terdeteksi" in (m.text or ""))
        assert "20 Jun 2024" in card.text  # beda tahun → tahun ditampilkan
        assert "Hari ini" not in card.text

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
        assert txs[0].occurred_at.isoformat() == "2024-06-20"

    async def test_quick_add_multi_items_queue(self, app_dispatcher, session_factory, monkeypatch):
        """Pesan multi-item → kartu per item berurutan (1/2 → 2/2), semua tersimpan."""
        from sqlalchemy import select

        from app.ai import client as ai_client
        from app.db.models import Transaction

        async def fake_complete_json(session, messages, *, temperature=0.0):
            return {"action": "multi", "confidence": "high",
                    "items": [
                        {"type": "expense", "amount": 50000,
                         "category_guess": "Makan & Minum", "note": "2 kopi kenangan"},
                        {"type": "expense", "amount": 60000,
                         "category_guess": "Makan & Minum", "note": "2 KFC"},
                    ]}

        monkeypatch.setattr(ai_client, "complete_json", fake_complete_json)

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(
            update_id=1,
            message=make_msg(123, 123, "kemarin\nkopi kenangan 2 50000\nKFC 2 60000"),
        ))

        sent = api_calls(SendMessage)
        card1 = next(m for m in sent if "Transaksi Terdeteksi" in (m.text or ""))
        assert "(1/2)" in card1.text
        assert "Rp 50.000" in card1.text

        for i in (1, 2):  # dua kali save
            cb = CallbackQuery(
                id=str(i),
                from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
                chat_instance="ci",
                message=make_msg(123, 123, "junk"),
                data="qa:save",
            )
            await dp.feed_update(bot, Update(update_id=1 + i, callback_query=cb))

        edits = api_calls(EditMessageText)
        assert any("(2/2)" in (m.text or "") for m in edits)  # kartu kedua muncul
        assert any("✅ Tersimpan!" in (m.text or "") for m in edits)  # final

        async with session_factory() as s:
            txs = (await s.execute(select(Transaction))).scalars().all()
        assert len(txs) == 2
        assert sorted(t.amount for t in txs) == [50000.00, 60000.00]

    async def test_quick_add_multi_skip_one_item(self, app_dispatcher, session_factory, monkeypatch):
        """⏭️ Lewati Item di kartu multi → hanya item itu yang dibatalkan, sisanya jalan."""
        from sqlalchemy import select

        from app.ai import client as ai_client
        from app.db.models import Transaction

        async def fake_complete_json(session, messages, *, temperature=0.0):
            return {"action": "multi", "confidence": "high",
                    "items": [
                        {"type": "expense", "amount": 50000,
                         "category_guess": "Makan & Minum", "note": "2 kopi kenangan"},
                        {"type": "expense", "amount": 60000,
                         "category_guess": "Makan & Minum", "note": "2 KFC"},
                    ]}

        monkeypatch.setattr(ai_client, "complete_json", fake_complete_json)

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(
            update_id=1,
            message=make_msg(123, 123, "kemarin\nkopi kenangan 2 50000\nKFC 2 60000"),
        ))

        sent = api_calls(SendMessage)
        card1 = next(m for m in sent if "Transaksi Terdeteksi" in (m.text or ""))
        assert "(1/2)" in card1.text
        buttons = [b.text for row in card1.reply_markup.inline_keyboard for b in row]
        assert "⏭️ Lewati Item" in buttons
        assert "❌ Batal" in buttons  # batal tetap = batal SEMUA antrian

        skip = CallbackQuery(
            id="10",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="qa:skip",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=skip))

        edits = api_calls(EditMessageText)
        assert any("(2/2)" in (m.text or "") for m in edits)  # kartu item 2 muncul
        assert any("Rp 60.000" in (m.text or "") for m in edits)

        save = CallbackQuery(
            id="11",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="qa:save",
        )
        await dp.feed_update(bot, Update(update_id=3, callback_query=save))
        edits = api_calls(EditMessageText)
        assert any("✅ Tersimpan!" in (m.text or "") for m in edits)

        async with session_factory() as s:
            txs = (await s.execute(select(Transaction))).scalars().all()
        assert len(txs) == 1  # item 1 dilewati, hanya item 2 tersimpan
        assert txs[0].amount == 60000.00

    async def test_quick_add_multi_skip_last_item_cancels(self, app_dispatcher, session_factory, monkeypatch):
        """Lewati item terakhir (antrian habis) → kartu ditutup, tidak ada yang tersimpan."""
        from sqlalchemy import select

        from app.ai import client as ai_client
        from app.db.models import Transaction

        async def fake_complete_json(session, messages, *, temperature=0.0):
            return {"action": "multi", "confidence": "high",
                    "items": [
                        {"type": "expense", "amount": 50000,
                         "category_guess": "Makan & Minum", "note": "2 kopi kenangan"},
                        {"type": "expense", "amount": 60000,
                         "category_guess": "Makan & Minum", "note": "2 KFC"},
                    ]}

        monkeypatch.setattr(ai_client, "complete_json", fake_complete_json)

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(
            update_id=1,
            message=make_msg(123, 123, "kemarin\nkopi kenangan 2 50000\nKFC 2 60000"),
        ))

        # kartu item 1 dilewati → kartu item 2 muncul → juga dilewati → antrian habis
        for i in (2, 3):
            skip = CallbackQuery(
                id=str(i),
                from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
                chat_instance="ci",
                message=make_msg(123, 123, "junk"),
                data="qa:skip",
            )
            await dp.feed_update(bot, Update(update_id=i, callback_query=skip))

        edits = api_calls(EditMessageText)
        assert any("❌ Dibatalkan." in (m.text or "") for m in edits)

        async with session_factory() as s:
            txs = (await s.execute(select(Transaction))).scalars().all()
        assert len(txs) == 0

    # ==================== Laporan 3 level (/ringkasan → 📊 Laporan) ====================

    async def test_report_menu_3_level(self, app_dispatcher, session_factory, monkeypatch):
        """Laporan: /ringkasan → 📊 Laporan → Rentang → 3 Bulan; Spesifik → tahun → bulan."""
        from datetime import timedelta

        from app.utils.format import today_local
        from tests.conftest import make_category, make_tx

        today = today_local()
        this_month = today
        two_months_ago = (today - timedelta(days=62)).replace(day=10)
        eight_months_ago = (today - timedelta(days=250)).replace(day=20)

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            w = await make_wallet(s, u.id)
            c = await make_category(s, None)
            await make_tx(s, u.id, w.id, c.id, amount="25000", occurred_at=this_month)
            await make_tx(s, u.id, w.id, c.id, amount="15000", occurred_at=two_months_ago)
            await make_tx(s, u.id, w.id, c.id, amount="50000", occurred_at=eight_months_ago)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        def press(i: int, data: str):
            cb = CallbackQuery(
                id=str(i),
                from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
                chat_instance="ci",
                message=make_msg(123, 123, "junk"),
                data=data,
            )
            return dp.feed_update(bot, Update(update_id=i, callback_query=cb))

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/ringkasan")))

        # level 1: ringkasan default + tombol 📊 Laporan
        sent = api_calls(SendMessage)
        assert any("Hari Ini" in (m.text or "") for m in sent)
        assert any("📊 Laporan" in (b.text for row in sent[-1].reply_markup.inline_keyboard for b in row)
                   for m in sent if m.reply_markup)

        # level 2: menu laporan
        await press(2, "rep:menu")
        edits = api_calls(EditMessageText)
        assert any("Pilih jenis laporan" in (m.text or "") for m in edits)

        # level 3a: rentang → 3 bulan terakhir (bulan ini + 2 sebelumnya)
        await press(3, "rep:range")
        edits = api_calls(EditMessageText)
        assert any("Pilih rentang waktu" in (m.text or "") for m in edits)
        await press(4, "rep:r:3")
        edits = api_calls(EditMessageText)
        rep = next(m for m in edits if "Rentang 3 Bulan Terakhir" in (m.text or ""))
        assert "Rp 40.000" in rep.text  # 25000 + 15000; tx 8 bulan lalu di luar
        assert "2 transaksi" in rep.text

        # level 3b: spesifik → tahun → bulan (sesuai data yang ada)
        await press(5, "rep:spec")
        edits = api_calls(EditMessageText)
        year_picker = next(m for m in edits if "Pilih tahun" in (m.text or ""))
        old_year = eight_months_ago.year
        assert any(b.callback_data == f"rep:y:{old_year}"
                   for row in year_picker.reply_markup.inline_keyboard for b in row)

        await press(6, f"rep:y:{old_year}")
        edits = api_calls(EditMessageText)
        month_picker = next(m for m in edits if f"Pilih Bulan — {old_year}" in (m.text or ""))
        old_month = eight_months_ago.month
        assert any(b.callback_data == f"rep:m:{old_year:04d}-{old_month:02d}"
                   for row in month_picker.reply_markup.inline_keyboard for b in row)

        await press(7, f"rep:m:{old_year:04d}-{old_month:02d}")
        edits = api_calls(EditMessageText)
        from app.handlers.summary import MONTHS_FULL
        month_rep = next(m for m in edits if f"{MONTHS_FULL[old_month - 1]} {old_year}" in (m.text or ""))
        assert "Rp 50.000" in month_rep.text
        assert "1 transaksi" in month_rep.text

    async def test_report_specific_empty(self, app_dispatcher, session_factory, monkeypatch):
        """Spesifik tanpa data transaksi → pesan belum ada data + tombol kembali."""
        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/ringkasan")))
        cb = CallbackQuery(
            id="2",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="rep:spec",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))

        edits = api_calls(EditMessageText)
        assert any("Belum ada data transaksi" in (m.text or "") for m in edits)

    # ==================== Portal menu utama (/menu) ====================

    async def test_menu_hub_and_views(self, app_dispatcher, session_factory, monkeypatch):
        """/menu → hub semua fitur; tombol view me-render di pesan hub (in-place)."""
        from tests.conftest import make_category, make_tx

        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            w = await make_wallet(s, u.id)
            c = await make_category(s, None)
            await make_tx(s, u.id, w.id, c.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/menu")))

        sent = api_calls(SendMessage)
        hub = next(m for m in sent if "Menu Utama" in (m.text or ""))
        assert "Test User" in hub.text  # header identitas user
        assert "@tester" in hub.text
        buttons = [b.text for row in hub.reply_markup.inline_keyboard for b in row]
        for label in ("💸 Catat Transaksi", "📋 Riwayat", "📊 Laporan", "👛 Wallet",
                      "🔄 Transfer", "🎯 Budget", "🏷️ Kategori", "🧠 Insight AI",
                      "📈 Status", "💎 Upgrade Premium", "⚙️ Pengaturan",
                      "📤 Export CSV", "📖 Bantuan"):
            assert label in buttons

        def press(i: int, data: str):
            cb = CallbackQuery(
                id=str(i),
                from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
                chat_instance="ci",
                message=make_msg(123, 123, "junk"),
                data=data,
            )
            return dp.feed_update(bot, Update(update_id=i, callback_query=cb))

        await press(2, "menu:go:riwayat")
        edits = api_calls(EditMessageText)
        assert any("Riwayat Transaksi" in (m.text or "") for m in edits)

        await press(3, "menu:go:laporan")
        edits = api_calls(EditMessageText)
        assert any("Hari Ini" in (m.text or "") for m in edits)

        await press(4, "menu:go:status")
        edits = api_calls(EditMessageText)
        assert any("Saldo" in (m.text or "") for m in edits)

        await press(5, "menu:back")
        edits = api_calls(EditMessageText)
        assert any("Menu Utama" in (m.text or "") for m in edits)

    async def test_menu_catat_starts_flow_as_new_message(self, app_dispatcher,
                                                         session_factory, monkeypatch):
        """Tombol alur (💸 Catat) dari hub → FSM mulai dengan pesan BARU."""
        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            u = await make_user(s, tg_id=123)
            await make_wallet(s, u.id)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/menu")))
        cb = CallbackQuery(
            id="2",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="menu:go:catat",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))

        sent = api_calls(SendMessage)
        assert any("Mau catat apa" in (m.text or "") for m in sent)  # prompt FSM pesan baru
        await ctx.clear()  # jangan bocorkan state FSM ke test lain

    async def test_start_existing_user_opens_summary_with_menu_button(self, app_dispatcher,
                                                                      session_factory, monkeypatch):
        """/start user lama → view ringkasan (sama dengan /ringkasan) + tombol 🏠 Menu."""
        dp, storage = app_dispatcher
        dp["session_factory"] = session_factory
        async with session_factory() as s:
            await make_user(s, tg_id=123)
            await s.commit()
        bot = await make_bot(monkeypatch)
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=bot.id, chat_id=123, user_id=123))
        await ctx.clear()

        await dp.feed_update(bot, Update(update_id=1, message=make_msg(123, 123, "/start")))

        sent = api_calls(SendMessage)
        view = next(m for m in sent if "Hari Ini" in (m.text or ""))
        buttons = [b.text for row in view.reply_markup.inline_keyboard for b in row]
        assert any(b.endswith("📅 Hari") for b in buttons)  # periode aktif ada tanda ✅
        assert "📆 Minggu" in buttons and "🗓️ Bulan" in buttons
        assert "📊 Laporan" in buttons
        assert "🏠 Menu" in buttons  # tombol tambahan ke menu utama
        assert not any("Halo lagi" in (m.text or "") for m in sent)

        # tekan 🏠 Menu → portal menu utama terbuka (di tempat)
        cb = CallbackQuery(
            id="2",
            from_user=TgUser(id=123, is_bot=False, first_name="Tester"),
            chat_instance="ci",
            message=make_msg(123, 123, "junk"),
            data="menu:back",
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=cb))
        edits = api_calls(EditMessageText)
        assert any("Menu Utama" in (m.text or "") for m in edits)
