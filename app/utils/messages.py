"""Helper render pesan Telegram: pola edit-message (PRD §7) + fallback kirim baru."""

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

async def edit_or_send(bot, chat_id: int, message_id: int | None, text: str,
                       kb: InlineKeyboardMarkup | None = None) -> int:
    """Edit message kalau masih bisa, kalau gagal kirim baru. Return message_id baru."""
    if message_id:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id,
                reply_markup=kb, parse_mode=ParseMode.HTML,
            )
            return message_id
        except TelegramBadRequest:
            pass
    sent = await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return sent.message_id


async def render_step(bot, chat_id: int, state, text: str,
                      kb: InlineKeyboardMarkup | None = None) -> None:
    """Render prompt FSM: edit pesan prompt sebelumnya kalau ada, update msg_id di FSM data."""
    data = await state.get_data()
    msg_id = await edit_or_send(bot, chat_id, data.get("msg_id"), text, kb)
    await state.update_data(msg_id=msg_id)
