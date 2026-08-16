"""Layanan budget: kalkulasi pemakaian & notifikasi alert (PRD §5.1)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Budget
from app.domain.logic import budget_alert
from app.domain.periods import period_window
from app.repositories.budgets import BudgetRepo
from app.repositories.categories import CategoryRepo
from app.repositories.transactions import TransactionRepo
from app.repositories.wallets import WalletRepo
from app.services.errors import ValidationError
from app.utils.format import today_local


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(
        self,
        user_id: int,
        *,
        category_id: int | None,
        wallet_id: int | None,
        period_type: str,
        amount: Decimal,
    ) -> Budget:
        amount = Decimal(amount).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValidationError("Jumlah budget harus lebih dari 0.")
        if period_type not in ("weekly", "monthly"):
            raise ValidationError("Periode budget tidak valid.")
        if category_id is not None:
            category = await CategoryRepo(self.s).get_usable(category_id, user_id)
            if not category or category.type != "expense":
                raise ValidationError("Kategori budget harus kategori pengeluaran.")
        if wallet_id is not None:
            wallet = await WalletRepo(self.s).get_for_user(wallet_id, user_id)
            if not wallet:
                raise ValidationError("Wallet tidak ditemukan.")
        return await BudgetRepo(self.s).create(
            user_id, category_id, wallet_id, period_type, amount
        )

    async def usage(self, budget: Budget, on_date: date) -> Decimal:
        """Pemakaian budget pada periode yang memuat on_date."""
        start, end = period_window(budget.period_type, on_date)
        return await TransactionRepo(self.s).expense_sum(
            budget.user_id, start, end, budget.category_id, budget.wallet_id
        )

    async def list_with_usage(self, user_id: int) -> list[tuple[Budget, Decimal]]:
        today = today_local()
        budgets = await BudgetRepo(self.s).list_by_user(user_id, active_only=False)
        result = []
        for b in budgets:
            result.append((b, await self.usage(b, today) if b.is_active else Decimal("0")))
        return result

    async def _matching_budgets(
        self, user_id: int, occurred_at: date, category_id: int, wallet_id: int
    ) -> list[Budget]:
        """Budget aktif yang relevan untuk transaksi ini (PRD §5.1 budget alert)."""
        budgets = await BudgetRepo(self.s).list_by_user(user_id, active_only=True)
        out = []
        for b in budgets:
            if b.category_id not in (None, category_id):
                continue
            if b.wallet_id not in (None, wallet_id):
                continue
            start, end = period_window(b.period_type, occurred_at)
            if start <= occurred_at <= end:
                out.append(b)
        return out

    async def alerts_for_new_expense(
        self, user_id: int, amount: Decimal, category_id: int, wallet_id: int, occurred_at: date
    ) -> list[str]:
        """Notifikasi budget untuk transaksi pengeluaran baru (dipanggil SEBELUM insert).

        Alert hanya dikirim saat transaksi ini menyentuh threshold/melewati limit
        (sebelumnya di bawah, sekarang di atas) — tidak spam tiap transaksi.
        """
        alerts = []
        for b in await self._matching_budgets(user_id, occurred_at, category_id, wallet_id):
            start, end = period_window(b.period_type, occurred_at)
            before = await TransactionRepo(self.s).expense_sum(
                user_id, start, end, b.category_id, b.wallet_id
            )
            after = before + amount
            kind = budget_alert(before, after, b.amount, b.alert_threshold_pct)
            if kind == "warn":
                pct = int(after / b.amount * 100)
                alerts.append(
                    f"⚠️ <b>Budget hampir habis!</b>\n{budget_name_label(b)} "
                    f"terpakai {pct}% (batas {b.alert_threshold_pct}%)."
                )
            elif kind == "over":
                alerts.append(
                    f"🔴 <b>Budget terlampaui!</b>\n{budget_name_label(b)} sudah melewati batas. "
                    "Saatnya rem pengeluaran 💪"
                )
        return alerts

    async def delete(self, user_id: int, budget_id: int) -> None:
        budget = await BudgetRepo(self.s).get_for_user(budget_id, user_id)
        if not budget:
            raise ValidationError("Budget tidak ditemukan.")
        await BudgetRepo(self.s).delete(budget)

    async def toggle(self, user_id: int, budget_id: int) -> Budget:
        budget = await BudgetRepo(self.s).get_for_user(budget_id, user_id)
        if not budget:
            raise ValidationError("Budget tidak ditemukan.")
        budget.is_active = not budget.is_active
        return budget


def budget_name_label(budget: Budget) -> str:
    if budget.category_id:
        return "Budget kategori"
    return "Budget total"
