"""Layanan ringkasan/laporan (PRD §5.1): agregasi per periode, per kategori.

Transfer antar wallet TIDAK ikut laporan income/expense (tabel terpisah — PRD §4).
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.periods import month_window, period_window, previous_month, shift_date
from app.repositories.transactions import TransactionRepo


class SummaryService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def build_summary(
        self,
        user_id: int,
        period_type: str,
        on_date: date,
        wallet_id: int | None = None,
    ) -> dict:
        start, end = period_window(period_type, on_date)
        repo = TransactionRepo(self.s)
        income, expense = await repo.totals(user_id, start, end, wallet_id)
        by_category = await repo.category_breakdown(user_id, start, end, wallet_id)
        tx_count = await repo.count_in_window(user_id, start, end)

        prev_date = shift_date(period_type, on_date, -1)
        prev_start, prev_end = period_window(period_type, prev_date)
        prev_income, prev_expense = await repo.totals(user_id, prev_start, prev_end, wallet_id)

        return {
            "period_type": period_type,
            "start": start,
            "end": end,
            "income": income,
            "expense": expense,
            "net": income - expense,
            "tx_count": tx_count,
            "by_category": by_category[:8],
            "prev_income": prev_income,
            "prev_expense": prev_expense,
        }

    async def build_range_summary(self, user_id: int, start: date, end: date) -> dict:
        """Ringkasan untuk rentang tanggal bebas (mis. N bulan terakhir).

        Perbandingan "periode sebelumnya" = rentang sama panjang tepat sebelum start.
        """
        repo = TransactionRepo(self.s)
        income, expense = await repo.totals(user_id, start, end)
        by_category = await repo.category_breakdown(user_id, start, end)
        tx_count = await repo.count_in_window(user_id, start, end)

        length = (end - start).days + 1
        prev_start = start - timedelta(days=length)
        prev_end = start - timedelta(days=1)
        _, prev_expense = await repo.totals(user_id, prev_start, prev_end)

        return {
            "start": start,
            "end": end,
            "income": income,
            "expense": expense,
            "net": income - expense,
            "tx_count": tx_count,
            "by_category": by_category[:8],
            "prev_expense": prev_expense,
        }

    async def month_aggregates(self, user_id: int, month_date: date) -> dict:
        """Agregat satu bulan kalender + perbandingan bulan sebelumnya.

        Dipakai untuk AI insight (hanya angka agregat yang dikirim ke AI — PRD §5.4).
        """
        start, end = month_window(month_date)
        repo = TransactionRepo(self.s)
        income, expense = await repo.totals(user_id, start, end)
        by_category = await repo.category_breakdown(user_id, start, end)
        tx_count = await repo.count_in_window(user_id, start, end)

        prev = previous_month(month_date)
        p_start, p_end = month_window(prev)
        prev_income, prev_expense = await repo.totals(user_id, p_start, p_end)

        return {
            "month_label": f"{month_date.year:04d}-{month_date.month:02d}",
            "income": income,
            "expense": expense,
            "net": income - expense,
            "tx_count": tx_count,
            "by_category": by_category,
            "prev_month_label": f"{prev.year:04d}-{prev.month:02d}",
            "prev_income": prev_income,
            "prev_expense": prev_expense,
        }


def pct_delta(current: Decimal, previous: Decimal) -> str | None:
    """Persentase perubahan vs periode sebelumnya, untuk tampilan laporan."""
    if previous == 0:
        return None
    delta = (current - previous) / previous * 100
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
    return f"{arrow} {abs(delta):.0f}%"
