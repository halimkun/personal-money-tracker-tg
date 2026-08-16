"""Layanan wallet: saldo on-the-fly, CRUD, validasi (PRD §4 & §5.1)."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Wallet
from app.domain.logic import compute_balance
from app.repositories.transactions import TransactionRepo
from app.repositories.transfers import TransferRepo
from app.repositories.wallets import WalletRepo
from app.services.errors import ValidationError


class WalletService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(
        self, user_id: int, name: str, type_: str, initial_balance: Decimal
    ) -> Wallet:
        repo = WalletRepo(self.s)
        name = name.strip()
        if not name:
            raise ValidationError("Nama wallet tidak boleh kosong.")
        if len(name) > 100:
            raise ValidationError("Nama wallet maksimal 100 karakter.")
        existing = await repo.list_by_user(user_id, active_only=True)
        is_default = not existing  # wallet pertama otomatis default
        return await repo.create(user_id, name, type_, initial_balance, is_default=is_default)

    async def list_with_balances(self, user_id: int) -> list[tuple[Wallet, Decimal]]:
        """Semua wallet (termasuk nonaktif, ditandai) + saldo hasil agregasi."""
        wallets = await WalletRepo(self.s).list_by_user(user_id, active_only=False)
        balances = await self.balances_by_wallet(user_id)
        return [(w, balances.get(w.id, Decimal("0"))) for w in wallets]

    async def balances_by_wallet(self, user_id: int) -> dict[int, Decimal]:
        """Saldo per wallet dihitung on-the-fly (bukan kolom statis — PRD §4)."""
        tx_repo = TransactionRepo(self.s)
        tr_repo = TransferRepo(self.s)
        income = await tx_repo.sums_by_wallet(user_id, "income")
        expense = await tx_repo.sums_by_wallet(user_id, "expense")
        out = await tr_repo.out_by_wallet(user_id)
        into = await tr_repo.in_by_wallet(user_id)
        wallets = await WalletRepo(self.s).list_by_user(user_id, active_only=False)
        return {
            w.id: compute_balance(
                w.initial_balance,
                income.get(w.id, Decimal("0")),
                expense.get(w.id, Decimal("0")),
                out.get(w.id, Decimal("0")),
                into.get(w.id, Decimal("0")),
            )
            for w in wallets
        }

    async def balance(self, wallet_id: int) -> Decimal:
        wallet = await WalletRepo(self.s).get(wallet_id)
        if not wallet:
            raise ValidationError("Wallet tidak ditemukan.")
        balances = await self.balances_by_wallet(wallet.user_id)
        return balances.get(wallet_id, Decimal("0"))

    async def set_default(self, user_id: int, wallet_id: int) -> None:
        wallet = await WalletRepo(self.s).get_for_user(wallet_id, user_id)
        if not wallet or not wallet.is_active:
            raise ValidationError("Wallet tidak ditemukan/nonaktif.")
        await WalletRepo(self.s).set_default(user_id, wallet_id)

    async def rename(self, user_id: int, wallet_id: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValidationError("Nama wallet tidak boleh kosong.")
        wallet = await WalletRepo(self.s).get_for_user(wallet_id, user_id)
        if not wallet:
            raise ValidationError("Wallet tidak ditemukan.")
        wallet.name = new_name[:100]

    async def deactivate(self, user_id: int, wallet_id: int) -> None:
        repo = WalletRepo(self.s)
        wallet = await repo.get_for_user(wallet_id, user_id)
        if not wallet:
            raise ValidationError("Wallet tidak ditemukan.")
        active = await repo.list_by_user(user_id, active_only=True)
        if len(active) <= 1 and wallet.is_active:
            raise ValidationError("Minimal harus ada 1 wallet aktif.")
        wallet.is_active = False
        if wallet.is_default:
            wallet.is_default = False
            others = [w for w in active if w.id != wallet_id]
            if others:
                others[0].is_default = True
