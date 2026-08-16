"""Middleware sesi DB: 1 sesi per update, commit di akhir, rollback kalau error."""

import logging

from aiogram import BaseMiddleware

log = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        session_factory = data["session_factory"]
        async with session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                log.exception("error di update %s", type(event).__name__)
                raise
