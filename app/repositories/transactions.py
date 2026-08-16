from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Transaction
from app.repositories.base import BaseRepo


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


class TransactionRepo(BaseRepo):
    async def get_for_user(self, tx_id: int, user_id: int) -> Transaction | None:
        return await self.s.scalar(
            select(Transaction).where(Transaction.id == tx_id, Transaction.user_id == user_id)
        )

    async def create(self, **fields) -> Transaction:
        return await self.add(Transaction(**fields))

    async def list_paginated(
        self,
        user_id: int,
        page: int,
        per_page: int,
        type_: str | None = None,
        wallet_id: int | None = None,
        category_id: int | None = None,
    ) -> tuple[list[tuple[Transaction, str, str]], int]:
        """List transaksi join kategori. Return (rows, total) — row = (tx, cat_name, cat_icon)."""
        q = (
            select(Transaction, Category.name, Category.icon)
            .join(Category, Transaction.category_id == Category.id)
            .where(Transaction.user_id == user_id)
        )
        if type_:
            q = q.where(Transaction.type == type_)
        if wallet_id:
            q = q.where(Transaction.wallet_id == wallet_id)
        if category_id:
            q = q.where(Transaction.category_id == category_id)
        total = await self.s.scalar(
            select(func.count()).select_from(q.order_by(None).subquery())
        ) or 0
        rows = (
            await self.s.execute(
                q.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
                .offset(page * per_page)
                .limit(per_page)
            )
        ).all()
        return [(tx, name, icon) for tx, name, icon in rows], total

    async def sums_by_wallet(
        self, user_id: int, type_: str, start: date | None = None, end: date | None = None
    ) -> dict[int, Decimal]:
        q = (
            select(Transaction.wallet_id, func.sum(Transaction.amount))
            .where(Transaction.user_id == user_id, Transaction.type == type_)
            .group_by(Transaction.wallet_id)
        )
        if start:
            q = q.where(Transaction.occurred_at >= start)
        if end:
            q = q.where(Transaction.occurred_at <= end)
        rows = (await self.s.execute(q)).all()
        return {wid: _dec(total) for wid, total in rows}

    async def totals(
        self, user_id: int, start: date, end: date, wallet_id: int | None = None
    ) -> tuple[Decimal, Decimal]:
        """Total (income, expense) dalam jendela tanggal."""
        q = (
            select(Transaction.type, func.sum(Transaction.amount))
            .where(
                Transaction.user_id == user_id,
                Transaction.occurred_at >= start,
                Transaction.occurred_at <= end,
            )
            .group_by(Transaction.type)
        )
        if wallet_id:
            q = q.where(Transaction.wallet_id == wallet_id)
        rows = dict((await self.s.execute(q)).all())
        return _dec(rows.get("income")), _dec(rows.get("expense"))

    async def expense_sum(
        self,
        user_id: int,
        start: date,
        end: date,
        category_id: int | None = None,
        wallet_id: int | None = None,
    ) -> Decimal:
        """Total pengeluaran untuk kalkulasi budget."""
        q = select(func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.occurred_at >= start,
            Transaction.occurred_at <= end,
        )
        if category_id:
            q = q.where(Transaction.category_id == category_id)
        if wallet_id:
            q = q.where(Transaction.wallet_id == wallet_id)
        return _dec(await self.s.scalar(q))

    async def category_breakdown(
        self,
        user_id: int,
        start: date,
        end: date,
        wallet_id: int | None = None,
        type_: str = "expense",
    ) -> list[dict]:
        """Agregasi per kategori: [{name, icon, total, pct}] terurut dari terbesar."""
        q = (
            select(Category.name, Category.icon, func.sum(Transaction.amount))
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.user_id == user_id,
                Transaction.type == type_,
                Transaction.occurred_at >= start,
                Transaction.occurred_at <= end,
            )
            .group_by(Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        if wallet_id:
            q = q.where(Transaction.wallet_id == wallet_id)
        rows = (await self.s.execute(q)).all()
        total = sum(_dec(v) for _, _, v in rows)
        return [
            {"name": name, "icon": icon or "", "total": _dec(v), "pct": (_dec(v) / total * 100) if total else 0}
            for name, icon, v in rows
        ]

    async def count_in_window(self, user_id: int, start: date, end: date) -> int:
        return (
            await self.s.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.user_id == user_id,
                    Transaction.occurred_at >= start,
                    Transaction.occurred_at <= end,
                )
            )
            or 0
        )

    async def count_all(self, user_id: int | None = None) -> int:
        q = select(func.count()).select_from(Transaction)
        if user_id:
            q = q.where(Transaction.user_id == user_id)
        return await self.s.scalar(q) or 0

    async def count_all_in_window(self, start: date, end: date) -> int:
        """Jumlah transaksi semua user dalam jendela tanggal (untuk /stats)."""
        return (
            await self.s.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.occurred_at >= start, Transaction.occurred_at <= end)
            )
            or 0
        )

    async def list_for_export(self, user_id: int) -> list[Transaction]:
        rows = await self.s.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        )
        return list(rows)


def make_transaction_repo(session: AsyncSession) -> TransactionRepo:
    return TransactionRepo(session)
