"""Pengaturan personal user (PRD §6): toggle insight AI bulanan."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.keyboards.inline import ikb
from app.services.settings import SettingsService
from app.services.users import UserService
from app.utils.messages import edit_or_send

router = Router()


@router.message(Command("pengaturan"))
async def cmd_pengaturan(message: Message, session, user: User):
    daily = await SettingsService(session).ai_daily_limit()
    lines = [
        "⚙️ <b>Pengaturan</b>",
        "",
        f"🧠 Insight AI bulanan: {'🟢 aktif' if user.ai_insight_enabled else '🔴 nonaktif'}",
        f"💬 Kuota analisis AI harian: {daily} pesan/hari",
        "",
        "💡 Wallet default diatur dari menu /wallet (tombol ⭐).",
    ]
    toggle_label = "🔴 Nonaktifkan Insight AI" if user.ai_insight_enabled else "🟢 Aktifkan Insight AI"
    await edit_or_send(
        message.bot, message.chat.id, None, "\n".join(lines),
        ikb([[("🔄", "set:refresh"), (toggle_label, "set:tins")]]),
    )


@router.callback_query(F.data == "set:refresh")
async def set_refresh(cb: CallbackQuery, session, user: User):
    await cmd_pengaturan_rerender(cb, session, user)
    await cb.answer()


@router.callback_query(F.data == "set:tins")
async def set_toggle_insight(cb: CallbackQuery, session, user: User):
    new_status = await UserService(session).toggle_insight(user)
    await cb.answer(
        f"Insight AI {'diaktifkan ✅' if new_status else 'dinonaktifkan 🔴'}"
    )
    await cmd_pengaturan_rerender(cb, session, user)


async def cmd_pengaturan_rerender(cb: CallbackQuery, session, user: User):
    daily = await SettingsService(session).ai_daily_limit()
    lines = [
        "⚙️ <b>Pengaturan</b>",
        "",
        f"🧠 Insight AI bulanan: {'🟢 aktif' if user.ai_insight_enabled else '🔴 nonaktif'}",
        f"💬 Kuota analisis AI harian: {daily} pesan/hari",
        "",
        "💡 Wallet default diatur dari menu /wallet (tombol ⭐).",
    ]
    toggle_label = "🔴 Nonaktifkan Insight AI" if user.ai_insight_enabled else "🟢 Aktifkan Insight AI"
    await edit_or_send(
        cb.message.bot, cb.message.chat.id, cb.message.message_id, "\n".join(lines),
        ikb([[("🔄", "set:refresh"), (toggle_label, "set:tins")]]),
    )
