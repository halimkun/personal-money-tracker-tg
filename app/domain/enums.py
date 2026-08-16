"""Enum domain — tipe data inti aplikasi."""

from enum import StrEnum


class TxType(StrEnum):
    income = "income"
    expense = "expense"


class WalletType(StrEnum):
    cash = "cash"
    bank = "bank"
    ewallet = "ewallet"
    other = "other"


class PeriodType(StrEnum):
    weekly = "weekly"
    monthly = "monthly"


class TxSource(StrEnum):
    manual = "manual"
    ai_text = "ai_text"
    ai_image = "ai_image"


class PaymentStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


WALLET_TYPE_ICONS = {
    WalletType.cash.value: "💵",
    WalletType.bank.value: "🏦",
    WalletType.ewallet.value: "📱",
    WalletType.other.value: "💼",
}

WALLET_TYPE_LABELS = {
    WalletType.cash.value: "Tunai",
    WalletType.bank.value: "Bank",
    WalletType.ewallet.value: "E-Wallet",
    WalletType.other.value: "Lainnya",
}
