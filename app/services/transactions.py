"""Layanan transaksi: create/update/delete + cek freemium + alert budget (PRD §5.1, §5.3)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction, User
from app.domain.logic import can_add_transaction
from app.repositories.categories import CategoryRepo
from app.repositories.transactions import TransactionRepo
from app.repositories.wallets import WalletRepo
from app.services.budgets import BudgetService
from app.services.errors import FreemiumBlockedError, ValidationError
from app.services.settings import SettingsService


class TransactionService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def _check_freemium(self, user: User) -> None:
        settings_svc = SettingsService(self.s)
        payment_required = await settings_svc.payment_required()
        free_limit = await settings_svc.free_limit()
        allowed, reason = can_add_transaction(user, payment_required, free_limit)
        if not allowed:
            raise FreemiumBlockedError(reason)

    async def create(
        self,
        user: User,
        *,
        type_: str,
        amount: Decimal,
        category_id: int,
        wallet_id: int,
        note: str | None = None,
        occurred_at: date | None = None,
        source: str = "manual",
        source_file_id: str | None = None,
    ) -> tuple[Transaction, list[str]]:
        """Buat transaksi. Return (tx, daftar_alert_budget)."""
        if type_ not in ("income", "expense"):
            raise ValidationError("Tipe transaksi tidak valid.")
        amount = Decimal(amount).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValidationError("Jumlah harus lebih dari 0.")
        wallet = await WalletRepo(self.s).get_for_user(wallet_id, user.id)
        if not wallet or not wallet.is_active:
            raise ValidationError("Wallet tidak ditemukan/nonaktif.")
        category = await CategoryRepo(self.s).get_usable(category_id, user.id)
        if not category or category.type != type_:
            raise ValidationError("Kategori tidak valid untuk tipe transaksi ini.")

        await self._check_freemium(user)

        alerts: list[str] = []
        if type_ == "expense":
            alerts = await BudgetService(self.s).alerts_for_new_expense(
                user.id, amount, category_id, wallet_id, occurred_at
            )

        tx = await TransactionRepo(self.s).create(
            user_id=user.id,
            wallet_id=wallet_id,
            type=type_,
            amount=amount,
            category_id=category_id,
            note=(note or "").strip()[:500] or None,
            source=source,
            source_file_id=source_file_id,
            occurred_at=occurred_at or date.today(),
        )
        if not user.is_premium:
            user.free_transaction_count += 1
        return tx, alerts

    async def update(
        self,
        user: User,
        tx_id: int,
        *,
        amount: Decimal,
        category_id: int,
        note: str | None,
    ) -> Transaction:
        tx = await TransactionRepo(self.s).get_for_user(tx_id, user.id)
        if not tx:
            raise ValidationError("Transaksi tidak ditemukan.")
        amount = Decimal(amount).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValidationError("Jumlah harus lebih dari 0.")
        category = await CategoryRepo(self.s).get_usable(category_id, user.id)
        if not category or category.type != tx.type:
            raise ValidationError("Kategori tidak valid untuk tipe transaksi ini.")
        tx.amount = amount
        tx.category_id = category_id
        tx.note = (note or "").strip()[:500] or None
        return tx

    async def delete(self, user: User, tx_id: int) -> None:
        tx = await TransactionRepo(self.s).get_for_user(tx_id, user.id)
        if not tx:
            raise ValidationError("Transaksi tidak ditemukan.")
        await TransactionRepo(self.s).delete(tx)
