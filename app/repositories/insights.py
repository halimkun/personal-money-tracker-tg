from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIInsight
from app.repositories.base import BaseRepo


class InsightRepo(BaseRepo):
    async def create(self, user_id: int, period: str, content: str) -> AIInsight:
        return await self.add(AIInsight(user_id=user_id, period=period, content=content))

    async def get_for_user(self, insight_id: int, user_id: int) -> AIInsight | None:
        return await self.s.scalar(
            select(AIInsight).where(AIInsight.id == insight_id, AIInsight.user_id == user_id)
        )

    async def list_for_user(self, user_id: int, limit: int = 5) -> list[AIInsight]:
        rows = await self.s.scalars(
            select(AIInsight)
            .where(AIInsight.user_id == user_id)
            .order_by(AIInsight.created_at.desc())
            .limit(limit)
        )
        return list(rows)


def make_insight_repo(session: AsyncSession) -> InsightRepo:
    return InsightRepo(session)
