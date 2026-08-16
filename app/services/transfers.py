"""Layanan transfer antar wallet (PRD §4 & §5.1 — tabel terpisah dari transactions)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WalletTransfer
from app.domain.money import format_rupiah
from app.repositories.transfers import TransferRepo
from app.repositories.wallets import WalletRepo
from app.services.errors import ValidationError
from app.services.wallets import WalletService


class TransferService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(
        self,
        user: User,
        *,
        from_wallet_id: int,
        to_wallet_id: int,
        amount: Decimal,
        fee: Decimal = Decimal("0"),
        note: str | None = None,
        occurred_at: date | None = None,
    ) -> WalletTransfer:
        if from_wallet_id == to_wallet_id:
            raise ValidationError("Wallet asal dan tujuan tidak boleh sama.")
        amount = Decimal(amount).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValidationError("Jumlah harus lebih dari 0.")
        repo = WalletRepo(self.s)
        fw = await repo.get_for_user(from_wallet_id, user.id)
        tw = await repo.get_for_user(to_wallet_id, user.id)
        if not fw or not tw or not fw.is_active or not tw.is_active:
            raise ValidationError("Wallet tidak ditemukan/nonaktif.")

        balance = await WalletService(self.s).balance(fw.id)
        if balance < amount + fee:
            raise ValidationError(
                f"Saldo {fw.name} tidak cukup ({format_rupiah(balance)})."
            )

        return await TransferRepo(self.s).create(
            user_id=user.id,
            from_wallet_id=from_wallet_id,
            to_wallet_id=to_wallet_id,
            amount=amount,
            fee=fee,
            note=(note or "").strip()[:500] or None,
            occurred_at=occurred_at or date.today(),
        )
