from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CallbackRef
from app.repositories.base import BaseRepo


class CallbackRefRepo(BaseRepo):
    async def create(
        self, token: str, user_id: int, purpose: str, payload: dict[str, Any], expires_at: datetime
    ) -> CallbackRef:
        return await self.add(
            CallbackRef(token=token, user_id=user_id, purpose=purpose, payload=payload, expires_at=expires_at)
        )

    async def get(self, token: str) -> CallbackRef | None:
        return await self.s.get(CallbackRef, token)

    async def cleanup(self, cutoff: datetime) -> int:
        """Hapus token yang sudah kedaluwarsa atau sudah terpakai (PRD §7c housekeeping)."""
        result = await self.s.execute(
            delete(CallbackRef).where(
                (CallbackRef.expires_at < cutoff)
                | (CallbackRef.used_at.is_not(None) & (CallbackRef.used_at < cutoff))
            )
        )
        return result.rowcount or 0


def make_callback_ref_repo(session: AsyncSession) -> CallbackRefRepo:
    return CallbackRefRepo(session)
