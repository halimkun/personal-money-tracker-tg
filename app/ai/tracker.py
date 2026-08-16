"""Rate limiter quick-add AI per user per hari (PRD §5.1b & §10 poin 6).

In-memory — cukup untuk 1 proses bot; reset otomatis tiap hari (zona waktu lokal).
Limit dibaca dari global_settings (default dari env AI_DAILY_LIMIT).
"""

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.settings import SettingsService


class DailyRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[int, tuple[date, int]] = {}

    def _today(self) -> date:
        return datetime.now(settings.tz).date()

    async def allow(self, session: AsyncSession, user_id: int) -> bool:
        limit = await SettingsService(session).ai_daily_limit()
        today = self._today()
        d, n = self._counts.get(user_id, (today, 0))
        if d != today:
            return True
        return n < limit

    def record(self, user_id: int) -> None:
        today = self._today()
        d, n = self._counts.get(user_id, (today, 0))
        self._counts[user_id] = (today, n + 1 if d == today else 1)


rate_limiter = DailyRateLimiter()
