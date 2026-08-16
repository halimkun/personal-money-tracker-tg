class ValidationError(Exception):
    """Kesalahan input/bisnis yang layak ditampilkan ke user."""


class FreemiumBlockedError(Exception):
    """User non-premium sudah melewati batas transaksi gratis (PRD §5.3)."""
