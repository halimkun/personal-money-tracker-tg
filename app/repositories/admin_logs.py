from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminLog
from app.repositories.base import BaseRepo


class AdminLogRepo(BaseRepo):
    async def add(self, admin_id: int, action: str, detail: dict[str, Any] | None = None) -> AdminLog:
        return await BaseRepo.add(self, AdminLog(admin_id=admin_id, action=action, detail=detail))


def make_admin_log_repo(session: AsyncSession) -> AdminLogRepo:
    return AdminLogRepo(session)
