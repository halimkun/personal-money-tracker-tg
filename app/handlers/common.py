"""Command umum: /start, /help, /status, /cancel (PRD §6)."""

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.handlers.states import WalletStates
from app.scheduler.drafts import draft_registry
from app.services.users import UserService
from app.texts.id import HELP_TEXT, WELCOME_NEW
from app.utils.messages import render_step

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state, session):
    tg = message.from_user
    user, is_new = await UserService(session).register(tg.id, tg.username, tg.full_name)

    if not is_new:
        # user lama: view ringkasan (sama dengan /ringkasan) + tombol 🏠 Menu
        from app.handlers import summary
        await summary._render(message.bot, message.chat.id, None, session, user,
                              "day", with_menu_button=True)
        return

    await message.answer(WELCOME_NEW)
    await state.set_state(WalletStates.entering_name)
    await state.update_data(wallet_task="start")
    await render_step(
        message.bot, message.chat.id, state,
        "💼 Beri nama wallet pertamamu (mis. <b>Cash</b>, <b>BCA</b>, <b>GoPay</b>):",
    )


@router.message(Command("help", "bantuan"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message, session, user):
    await message.answer(await UserService(session).build_status_text(user))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state, user):
    """Safety net: batalkan alur FSM apa pun (PRD §6 & §7b)."""
    data = await state.get_data()
    card_id = data.get("card_msg_id")
    if card_id:
        try:
            await message.bot.edit_message_text(
                "❌ Dibatalkan oleh user",
                chat_id=message.chat.id,
                message_id=card_id,
            )
        except TelegramBadRequest:
            pass
    draft_registry.unregister(user.id)
    await state.clear()
    await message.answer("✅ Dibatalkan. Tidak ada data tersimpan.")
