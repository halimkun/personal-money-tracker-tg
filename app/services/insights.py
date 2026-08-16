"""Layanan AI insight bulanan (PRD §5.4) — agregat → AI → simpan → tampil."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIInsight, User
from app.domain.periods import month_label
from app.repositories.insights import InsightRepo
from app.services.errors import ValidationError
from app.services.settings import SettingsService
from app.services.summary import SummaryService


class InsightsService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def generate(self, user: User, month_date: date) -> str:
        """Generate + simpan insight untuk satu bulan. Return konten insight."""
        if not user.ai_insight_enabled:
            raise ValidationError("Insight AI nonaktif untuk akunmu — nyalakan di /pengaturan.")
        settings_svc = SettingsService(self.s)
        if not await settings_svc.insight_enabled_global():
            raise ValidationError("Fitur insight AI sedang dinonaktifkan admin.")

        aggregates = await SummaryService(self.s).month_aggregates(user.id, month_date)
        if aggregates["tx_count"] == 0:
            raise ValidationError("Tidak ada transaksi di bulan tersebut.")

        from app.ai import insight as ai_insight

        content = await ai_insight.generate(self.s, user.id, aggregates)
        await InsightRepo(self.s).create(user.id, month_label(month_date), content)
        return content

    async def history(self, user_id: int, limit: int = 5) -> list[AIInsight]:
        return await InsightRepo(self.s).list_for_user(user_id, limit)

    async def get(self, user_id: int, insight_id: int) -> AIInsight | None:
        return await InsightRepo(self.s).get_for_user(insight_id, user_id)
