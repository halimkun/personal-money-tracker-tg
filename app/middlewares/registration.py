"""Middleware registrasi: pastikan user terdaftar sebelum handler lain jalan.

/start dibiarkan lewat (handler-nya yang melakukan get-or-create).

Catatan aiogram: middleware yang diregistrasi di dp.update menerima objek
`Update` mentah (bukan Message/CallbackQuery) — event aslinya diambil lewat
`Update.event`.
"""

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, Update
from aiogram.types.update import UpdateTypeLookupError

from app.repositories.users import UserRepo


class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Update):
            return await handler(event, data)
        try:
            inner = event.event
        except UpdateTypeLookupError:
            return await handler(event, data)
        if not isinstance(inner, (Message, CallbackQuery)):
            return await handler(event, data)

        session = data.get("session")
        if session is None:
            return await handler(event, data)

        from_user = inner.from_user
        if from_user is None:  # channel post dll. — tidak ada akun yang diregistrasikan
            return await handler(event, data)

        tg_id = from_user.id
        user = await UserRepo(session).get_by_telegram_id(tg_id)
        if user is None:
            if isinstance(inner, Message):
                text = (inner.text or inner.caption or "").strip()
                if text.startswith("/start"):
                    return await handler(event, data)
                await inner.answer("Halo! Sebelum mulai, ketik /start dulu ya 🙂")
            else:  # CallbackQuery
                await inner.answer("Akun belum terdaftar. Ketik /start dulu ya 🙂", show_alert=True)
            return None

        data["user"] = user
        return await handler(event, data)
