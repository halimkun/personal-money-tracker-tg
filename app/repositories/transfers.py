from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Wallet, WalletTransfer
from app.repositories.base import BaseRepo


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


class TransferRepo(BaseRepo):
    async def create(self, **fields) -> WalletTransfer:
        return await self.add(WalletTransfer(**fields))

    async def out_by_wallet(self, user_id: int) -> dict[int, Decimal]:
        """Total transfer keluar (jumlah + biaya) per wallet asal."""
        rows = (
            await self.s.execute(
                select(
                    WalletTransfer.from_wallet_id,
                    func.sum(WalletTransfer.amount + WalletTransfer.fee),
                )
                .where(WalletTransfer.user_id == user_id)
                .group_by(WalletTransfer.from_wallet_id)
            )
        ).all()
        return {wid: _dec(v) for wid, v in rows}

    async def in_by_wallet(self, user_id: int) -> dict[int, Decimal]:
        """Total transfer masuk per wallet tujuan."""
        rows = (
            await self.s.execute(
                select(WalletTransfer.to_wallet_id, func.sum(WalletTransfer.amount))
                .where(WalletTransfer.user_id == user_id)
                .group_by(WalletTransfer.to_wallet_id)
            )
        ).all()
        return {wid: _dec(v) for wid, v in rows}

    async def list_for_export(self, user_id: int) -> list[tuple[WalletTransfer, str, str]]:
        """Transfer + nama wallet asal & tujuan (untuk export CSV)."""
        from_wallet = Wallet.__table__.alias("from_wallet")
        to_wallet = Wallet.__table__.alias("to_wallet")
        rows = (
            await self.s.execute(
                select(
                    WalletTransfer,
                    from_wallet.c.name.label("from_name"),
                    to_wallet.c.name.label("to_name"),
                )
                .join(from_wallet, WalletTransfer.from_wallet_id == from_wallet.c.id)
                .join(to_wallet, WalletTransfer.to_wallet_id == to_wallet.c.id)
                .where(WalletTransfer.user_id == user_id)
                .order_by(WalletTransfer.occurred_at.desc(), WalletTransfer.id.desc())
            )
        ).all()
        return [(tr, fn, tn) for tr, fn, tn in rows]

    async def count_all(self, user_id: int | None = None) -> int:
        q = select(func.count()).select_from(WalletTransfer)
        if user_id:
            q = q.where(WalletTransfer.user_id == user_id)
        return await self.s.scalar(q) or 0

    async def month_sum(self, user_id: int, start: date, end: date) -> tuple[Decimal, int]:
        """(total amount transfer, jumlah transfer) dalam jendela — untuk insight/statistik."""
        rows = (
            await self.s.execute(
                select(func.sum(WalletTransfer.amount), func.count())
                .where(
                    WalletTransfer.user_id == user_id,
                    WalletTransfer.occurred_at >= start,
                    WalletTransfer.occurred_at <= end,
                )
            )
        ).one()
        return _dec(rows[0]), int(rows[1] or 0)


def make_transfer_repo(session: AsyncSession) -> TransferRepo:
    return TransferRepo(session)
