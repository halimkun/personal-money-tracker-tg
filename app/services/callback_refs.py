"""Token callback: alias pendek untuk callback_data kompleks (PRD §7c).

Format callback_data: "cb:{token}" (± 13 byte — jauh di bawah batas 64 byte Telegram).
Validasi kepemilikan (user_id) & masa berlaku wajib saat resolve.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.callback_refs import CallbackRefRepo

_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CallbackRefService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.repo = CallbackRefRepo(session)

    async def create(
        self,
        user_id: int,
        purpose: str,
        payload: dict[str, Any],
        ttl_minutes: int | None = None,
    ) -> str:
        """Buat token baru, return token-nya. Retry kalau bentrok (PK)."""
        from sqlalchemy.exc import IntegrityError

        ttl = ttl_minutes or settings.callback_ref_ttl_minutes
        for _ in range(3):
            token = "".join(secrets.choice(_ALPHABET) for _ in range(10))
            try:
                await self.repo.create(token, user_id, purpose, payload, _now_utc() + timedelta(minutes=ttl))
                return token
            except IntegrityError:
                await self.s.rollback()
        raise RuntimeError("Gagal generate token callback unik.")

    async def resolve(
        self, token: str, user_id: int, mark_used: bool = False
    ) -> dict[str, Any] | None:
        """Validasi token → return payload. None = tidak valid/kedaluwarsa/milik orang lain."""
        ref = await self.repo.get(token)
        if not ref:
            return None
        now = _now_utc()
        if ref.user_id != user_id or ref.expires_at < now or ref.used_at is not None:
            return None
        if mark_used:
            ref.used_at = now
        return {**ref.payload, "purpose": ref.purpose}
