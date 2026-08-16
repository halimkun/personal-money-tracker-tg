from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Budget
from app.repositories.base import BaseRepo


class BudgetRepo(BaseRepo):
    async def get_for_user(self, budget_id: int, user_id: int) -> Budget | None:
        return await self.s.scalar(
            select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id)
        )

    async def list_by_user(self, user_id: int, active_only: bool = True) -> list[Budget]:
        q = select(Budget).where(Budget.user_id == user_id)
        if active_only:
            q = q.where(Budget.is_active.is_(True))
        rows = await self.s.scalars(q.order_by(Budget.id))
        return list(rows)

    async def create(
        self,
        user_id: int,
        category_id: int | None,
        wallet_id: int | None,
        period_type: str,
        amount: Decimal,
        alert_threshold_pct: int = 80,
    ) -> Budget:
        return await self.add(
            Budget(
                user_id=user_id,
                category_id=category_id,
                wallet_id=wallet_id,
                period_type=period_type,
                amount=amount,
                alert_threshold_pct=alert_threshold_pct,
            )
        )


def make_budget_repo(session: AsyncSession) -> BudgetRepo:
    return BudgetRepo(session)
