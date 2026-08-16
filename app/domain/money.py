"""Logika uang murni: parsing & format nominal — tanpa dependency DB/bot."""

import re
from decimal import Decimal, InvalidOperation

_SUFFIXES = {
    "k": 1_000,
    "rb": 1_000,
    "ribu": 1_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
    "m": 1_000_000,
}
_AMOUNT_RE = re.compile(r"^([\d.,]+)\s*([a-z]*)$", re.IGNORECASE)


def parse_amount(text: str, *, allow_zero: bool = False) -> Decimal | None:
    """Parse nominal dari input user: "25000", "25.000", "2,5jt", "25rb", "500".

    Titik diperlakukan sebagai pemisah ribuan, koma sebagai desimal.
    """
    t = (text or "").strip().lower().replace(" ", "")
    if not t:
        return None
    m = _AMOUNT_RE.match(t)
    if not m:
        return None
    raw, suffix = m.groups()
    if suffix and suffix not in _SUFFIXES:
        return None
    if "," in raw:
        if "." in raw:
            raw = raw.replace(".", "")
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        value = Decimal(raw) * _SUFFIXES.get(suffix, 1)
    except InvalidOperation:
        return None
    if value < 0 or (value == 0 and not allow_zero):
        return None
    return value.quantize(Decimal("0.01"))


def format_rupiah(amount: Decimal) -> str:
    """Format gaya Indonesia: "Rp 1.234.567" / "Rp 1.234.567,5" / "-Rp 50.000"."""
    value = Decimal(amount).quantize(Decimal("0.01"))
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, frac = divmod(int(value * 100), 100)
    body = f"{whole:,}".replace(",", ".")
    if frac:
        body += "," + f"{frac:02d}".rstrip("0")
    return f"{sign}Rp {body}"
