from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Transaction
from app.repositories.base import BaseRepo


class CategoryRepo(BaseRepo):
    async def get(self, category_id: int) -> Category | None:
        return await self.s.get(Category, category_id)

    async def get_usable(self, category_id: int, user_id: int) -> Category | None:
        """Kategori milik user ATAU kategori global (user_id NULL)."""
        return await self.s.scalar(
            select(Category).where(
                Category.id == category_id,
                (Category.user_id.is_(None)) | (Category.user_id == user_id),
            )
        )

    async def list_for_user(self, user_id: int) -> list[Category]:
        """Kategori global + custom user, global dulu."""
        rows = await self.s.scalars(
            select(Category)
            .where((Category.user_id.is_(None)) | (Category.user_id == user_id))
            .order_by(Category.user_id.is_not(None), Category.name)
        )
        return list(rows)

    async def list_custom(self, user_id: int) -> list[Category]:
        rows = await self.s.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.name)
        )
        return list(rows)

    async def create(
        self, user_id: int | None, name: str, type_: str, icon: str | None, keywords: list[str] | None
    ) -> Category:
        return await self.add(
            Category(user_id=user_id, name=name, type=type_, icon=icon, keywords=keywords or [])
        )

    async def count_usage(self, category_id: int) -> int:
        return (
            await self.s.scalar(
                select(func.count()).select_from(Transaction).where(Transaction.category_id == category_id)
            )
            or 0
        )

    async def get_global_fallback(self, type_: str) -> Category | None:
        """Kategori global 'Lainnya' untuk fallback klasifikasi AI."""
        return await self.s.scalar(
            select(Category).where(
                Category.user_id.is_(None), Category.type == type_, Category.name == "Lainnya"
            )
        )

    async def global_count(self) -> int:
        return (
            await self.s.scalar(
                select(func.count()).select_from(Category).where(Category.user_id.is_(None))
            )
            or 0
        )


def make_category_repo(session: AsyncSession) -> CategoryRepo:
    return CategoryRepo(session)
