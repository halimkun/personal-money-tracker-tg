from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, User
from app.repositories.base import BaseRepo


class PaymentRepo(BaseRepo):
    async def get(self, payment_id: int) -> Payment | None:
        return await self.s.get(Payment, payment_id)

    async def create(self, user_id: int, amount: Decimal, proof_file_id: str | None) -> Payment:
        return await self.add(
            Payment(user_id=user_id, amount=amount, proof_file_id=proof_file_id, status="pending")
        )

    async def list_pending(self) -> list[tuple[Payment, str | None]]:
        """Payment pending + username user (untuk notifikasi admin)."""
        rows = (
            await self.s.execute(
                select(Payment, User.username)
                .join(User, Payment.user_id == User.id)
                .where(Payment.status == "pending")
                .order_by(Payment.created_at)
            )
        ).all()
        return [(p, username) for p, username in rows]

    async def count_pending(self) -> int:
        return (
            await self.s.scalar(
                select(func.count()).select_from(Payment).where(Payment.status == "pending")
            )
            or 0
        )


def make_payment_repo(session: AsyncSession) -> PaymentRepo:
    return PaymentRepo(session)
