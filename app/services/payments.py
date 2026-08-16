"""Layanan pembayaran premium — Opsi A: transfer manual + approval admin (PRD §5.3)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, User
from app.repositories.payments import PaymentRepo
from app.repositories.users import UserRepo
from app.services.errors import ValidationError


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(self, user: User, amount: Decimal, proof_file_id: str) -> Payment:
        return await PaymentRepo(self.s).create(user.id, amount, proof_file_id)

    async def approve(self, payment: Payment, admin_id: int) -> User:
        if payment.status != "pending":
            raise ValidationError("Pembayaran ini sudah diproses.")
        user = await UserRepo(self.s).get(payment.user_id)
        if not user:
            raise ValidationError("User tidak ditemukan.")
        from app.services.settings import SettingsService

        days = await SettingsService(self.s).premium_duration_days()
        user.is_premium = True
        user.premium_until = _now_utc() + timedelta(days=days)
        payment.status = "approved"
        payment.approved_by = admin_id
        payment.approved_at = _now_utc()
        return user

    async def reject(self, payment: Payment, admin_id: int) -> User | None:
        if payment.status != "pending":
            raise ValidationError("Pembayaran ini sudah diproses.")
        user = await UserRepo(self.s).get(payment.user_id)
        payment.status = "rejected"
        payment.approved_by = admin_id
        payment.approved_at = _now_utc()
        return user
