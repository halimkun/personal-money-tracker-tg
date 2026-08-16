"""Logika bisnis murni: saldo wallet, batas freemium, keputusan alert budget."""

from decimal import Decimal


def compute_balance(
    initial: Decimal,
    income: Decimal,
    expense: Decimal,
    transfer_out: Decimal,
    transfer_in: Decimal,
) -> Decimal:
    """Saldo wallet dihitung on-the-fly (PRD §4 catatan desain):
    initial + Σincome − Σexpense − Σtransfer_out + Σtransfer_in."""
    return initial + income - expense - transfer_out + transfer_in


def can_add_transaction(user, payment_required: bool, free_limit: int) -> tuple[bool, str | None]:
    """Cek kebijakan freemium (PRD §5.3). Return (boleh, pesan_tolak)."""
    if not payment_required or user.is_premium:
        return True, None
    if user.free_transaction_count < free_limit:
        return True, None
    return False, "Kuota transaksi gratis kamu sudah habis."


def budget_alert(before: Decimal, after: Decimal, limit: Decimal, threshold_pct: int) -> str | None:
    """Putuskan apakah transaksi baru memicu notifikasi budget.

    Return "warn" (menyentuh threshold, mis. 80%), "over" (melewati 100%),
    atau None (tidak ada notifikasi) — pesan diformat oleh caller.
    """
    if limit <= 0:
        return None
    b = before / limit * 100
    a = after / limit * 100
    if b < 100 <= a:
        return "over"  # prioritas: melewati batas lebih penting dari sekadar warning
    if b < threshold_pct <= a:
        return "warn"
    return None
