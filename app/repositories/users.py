from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.repositories.base import BaseRepo


class UserRepo(BaseRepo):
    async def get_by_telegram_id(self, tg_id: int) -> User | None:
        return await self.s.scalar(select(User).where(User.telegram_id == tg_id))

    async def get(self, user_id: int) -> User | None:
        return await self.s.get(User, user_id)

    async def create(self, tg_id: int, username: str | None, full_name: str | None) -> User:
        user = User(telegram_id=tg_id, username=username, full_name=full_name)
        return await self.add(user)

    async def list_paginated(
        self, page: int, per_page: int, search: str | None = None
    ) -> tuple[list[User], int]:
        q = select(User)
        if search:
            like = f"%{search}%"
            q = q.where(
                or_(
                    User.username.ilike(like),
                    User.full_name.ilike(like),
                    User.telegram_id == search if search.isdigit() else False,
                )
            )
        total = await self.s.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = (await self.s.scalars(q.order_by(User.id).offset(page * per_page).limit(per_page))).all()
        return list(rows), total

    async def list_active(self) -> list[User]:
        rows = await self.s.scalars(select(User).where(User.is_active.is_(True)))
        return list(rows)

    async def list_insight_recipients(self) -> list[User]:
        """User aktif dengan insight AI menyala (PRD §5.4)."""
        rows = await self.s.scalars(
            select(User).where(User.is_active.is_(True), User.ai_insight_enabled.is_(True))
        )
        return list(rows)

    async def reset_free_counters(self) -> None:
        """Reset kuota gratis bulanan (job scheduler)."""
        await self.s.execute(update(User).values(free_transaction_count=0))

    async def expire_premiums(self, now) -> int:
        """Turunkan user premium yang masa berlakunya habis."""
        result = await self.s.execute(
            update(User)
            .where(User.is_premium.is_(True), User.premium_until.is_not(None), User.premium_until < now)
            .values(is_premium=False, premium_until=None)
        )
        return result.rowcount or 0

    async def count(self) -> int:
        return await self.s.scalar(select(func.count()).select_from(User)) or 0

    async def count_active(self) -> int:
        return (
            await self.s.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
            or 0
        )

    async def count_premium(self) -> int:
        return (
            await self.s.scalar(select(func.count()).select_from(User).where(User.is_premium.is_(True)))
            or 0
        )


def make_user_repo(session: AsyncSession) -> UserRepo:
    return UserRepo(session)
