"""Perhitungan jendela periode (harian/mingguan/bulanan) — murni, tanpa dependency."""

from datetime import date, timedelta


def day_window(d: date) -> tuple[date, date]:
    return d, d


def week_window(d: date) -> tuple[date, date]:
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def month_window(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return first, nxt - timedelta(days=1)


def period_window(period_type: str, d: date) -> tuple[date, date]:
    # terima dua kosakata: "day/week/month" (ringkasan) & "weekly/monthly" (budget)
    if period_type in ("day", "daily"):
        return day_window(d)
    if period_type in ("week", "weekly"):
        return week_window(d)
    return month_window(d)


def shift_date(period_type: str, d: date, delta: int) -> date:
    """Geser tanggal sebesar delta periode (untuk navigasi laporan)."""
    if period_type in ("day", "daily"):
        return d + timedelta(days=delta)
    if period_type in ("week", "weekly"):
        return d + timedelta(weeks=delta)
    month = d.year * 12 + (d.month - 1) + delta
    return date(month // 12, month % 12 + 1, 1)


def month_label(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def previous_month(d: date) -> date:
    return shift_date("month", d, -1)
