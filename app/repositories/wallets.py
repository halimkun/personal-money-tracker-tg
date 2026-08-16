from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Wallet
from app.repositories.base import BaseRepo


class WalletRepo(BaseRepo):
    async def get(self, wallet_id: int) -> Wallet | None:
        return await self.s.get(Wallet, wallet_id)

    async def get_for_user(self, wallet_id: int, user_id: int) -> Wallet | None:
        """Get wallet dengan validasi kepemilikan."""
        return await self.s.scalar(
            select(Wallet).where(Wallet.id == wallet_id, Wallet.user_id == user_id)
        )

    async def list_by_user(self, user_id: int, active_only: bool = True) -> list[Wallet]:
        q = select(Wallet).where(Wallet.user_id == user_id)
        if active_only:
            q = q.where(Wallet.is_active.is_(True))
        rows = await self.s.scalars(q.order_by(Wallet.id))
        return list(rows)

    async def get_default(self, user_id: int) -> Wallet | None:
        return await self.s.scalar(
            select(Wallet).where(Wallet.user_id == user_id, Wallet.is_default.is_(True))
        )

    async def create(
        self,
        user_id: int,
        name: str,
        type_: str,
        initial_balance: Decimal,
        is_default: bool = False,
    ) -> Wallet:
        return await self.add(
            Wallet(user_id=user_id, name=name, type=type_, initial_balance=initial_balance, is_default=is_default)
        )

    async def set_default(self, user_id: int, wallet_id: int) -> None:
        await self.s.execute(
            update(Wallet).where(Wallet.user_id == user_id).values(is_default=False)
        )
        await self.s.execute(
            update(Wallet).where(Wallet.id == wallet_id, Wallet.user_id == user_id).values(is_default=True)
        )

    async def count_active(self, user_id: int) -> int:
        from sqlalchemy import func

        return (
            await self.s.scalar(
                select(func.count())
                .select_from(Wallet)
                .where(Wallet.user_id == user_id, Wallet.is_active.is_(True))
            )
            or 0
        )


def make_wallet_repo(session: AsyncSession) -> WalletRepo:
    return WalletRepo(session)
