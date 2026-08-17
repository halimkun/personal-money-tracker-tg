"""Menu utama /menu — portal semua fitur (pola info/view: update di tempat).

Tombol view (riwayat/laporan/wallet/dst.) me-render view-nya DI PESAN hub
(in-place). Tombol alur (catat/transfer) memulai FSM dengan pesan baru
sesuai aturan transaksional; pesan hub tetap jadi portal.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.keyboards.inline import back_kb, ikb
from app.utils.messages import edit_or_send

router = Router()

HUB_BUTTONS = [
    ("💸 Catat Transaksi", "menu:go:catat"),
    ("📋 Riwayat", "menu:go:riwayat"),
    ("📊 Laporan", "menu:go:laporan"),
    ("👛 Wallet", "menu:go:wallet"),
    ("🔄 Transfer", "menu:go:transfer"),
    ("🎯 Budget", "menu:go:budget"),
    ("🏷️ Kategori", "menu:go:kategori"),
    ("🧠 Insight AI", "menu:go:insight"),
    ("📈 Status", "menu:go:status"),
    ("💎 Upgrade Premium", "menu:go:upgrade"),
    ("⚙️ Pengaturan", "menu:go:pengaturan"),
    ("📤 Export CSV", "menu:go:export"),
    ("📖 Bantuan", "menu:go:help"),
]


async def _render_menu(bot, chat_id: int, message_id: int | None, session, user: User) -> None:
    # header identitas user (sama formatnya dengan /status) + portal fitur
    header = f"👤 <b>{user.full_name or '—'}</b>"
    if user.username:
        header += f" (@{user.username})"
    text = f"{header}\n🏠 <b>Menu Utama</b>\n\nSemua fitur MoneyBot dari satu tempat:"
    rows = [HUB_BUTTONS[i : i + 2] for i in range(0, len(HUB_BUTTONS), 2)]
    await edit_or_send(bot, chat_id, message_id, text, ikb(rows))


@router.message(Command("menu"))
async def cmd_menu(message: Message, session, user: User):
    await _render_menu(message.bot, message.chat.id, None, session, user)


@router.callback_query(F.data == "menu:back")
async def menu_back(cb: CallbackQuery, session, user: User):
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer()


@router.callback_query(F.data.startswith("menu:go:"))
async def menu_go(cb: CallbackQuery, state, session, user: User):
    target = cb.data.split(":", 2)[2]
    bot, chat_id, mid = cb.message.bot, cb.message.chat.id, cb.message.message_id

    if target == "catat":
        from app.handlers.transactions import cmd_catat
        await cmd_catat(cb.message, state, session, user)
    elif target == "transfer":
        from app.handlers.transfer import cmd_transfer
        await cmd_transfer(cb.message, state, session, user)
    elif target == "riwayat":
        from app.handlers.transactions import _show_riwayat
        await _show_riwayat(bot, chat_id, mid, session, user, 0, "all", 0, 0)
    elif target == "laporan":
        from app.handlers.summary import _render
        await _render(bot, chat_id, mid, session, user, "day")
    elif target == "wallet":
        from app.handlers.wallets import _render_menu as render_wallets
        await render_wallets(bot, chat_id, mid, session, user)
    elif target == "kategori":
        from app.handlers.categories import _render_menu as render_categories
        await render_categories(bot, chat_id, mid, session, user)
    elif target == "budget":
        from app.handlers.budgets import _render_menu as render_budgets
        await render_budgets(bot, chat_id, mid, session, user)
    elif target == "insight":
        from app.handlers.insight import _render_menu as render_insight
        await render_insight(bot, chat_id, mid)
    elif target == "status":
        from app.services.users import UserService
        await edit_or_send(bot, chat_id, mid,
                           await UserService(session).build_status_text(user),
                           back_kb("menu:back"))
    elif target == "upgrade":
        from app.handlers.upgrade import _render as render_upgrade
        await render_upgrade(bot, chat_id, mid, session, user)
    elif target == "pengaturan":
        from app.handlers.settings import _render_menu as render_settings
        await render_settings(bot, chat_id, mid, session, user)
    elif target == "export":
        from app.handlers.export import run_export
        await run_export(bot, chat_id, session, user)
    elif target == "help":
        from app.texts.id import HELP_TEXT
        await edit_or_send(bot, chat_id, mid, HELP_TEXT, back_kb("menu:back"))
    await cb.answer()
