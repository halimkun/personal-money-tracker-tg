"""Format tanggal & teks untuk tampilan (layer presentasi)."""

from datetime import date, datetime

from app.config import settings

_MONTHS_ID = [
    "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]

WEEKDAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def fmt_date(d: date) -> str:
    return f"{d.day} {_MONTHS_ID[d.month - 1]} {d.year}"


def fmt_date_short(d: date) -> str:
    return f"{d.day} {_MONTHS_ID[d.month - 1]}"


def fmt_datetime(dt: datetime) -> str:
    from datetime import timezone

    # disimpan naive UTC → konversi ke zona waktu lokal
    local = dt.replace(tzinfo=timezone.utc).astimezone(settings.tz)
    return f"{fmt_date_short(local.date())} {local:%H:%M}"


def today_local() -> date:
    from datetime import datetime

    return datetime.now(settings.tz).date()


def now_utc_naive() -> datetime:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
