import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GlobalSetting
from app.repositories.base import BaseRepo


class GlobalSettingsRepo(BaseRepo):
    async def get(self, key: str) -> str | None:
        row = await self.s.get(GlobalSetting, key)
        return row.value if row else None

    async def set(self, key: str, value: str) -> None:
        row = await self.s.get(GlobalSetting, key)
        if row:
            row.value = value
        else:
            self.s.add(GlobalSetting(key=key, value=value))
        await self.s.flush()

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def incr_int(self, key: str, by: int = 1) -> int:
        current = int(await self.get(key) or 0) + by
        await self.set(key, str(current))
        return current


def make_settings_repo(session: AsyncSession) -> GlobalSettingsRepo:
    return GlobalSettingsRepo(session)
