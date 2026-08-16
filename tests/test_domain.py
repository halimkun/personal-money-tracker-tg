"""Test domain layer — murni, tanpa DB."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.domain.logic import budget_alert, can_add_transaction, compute_balance
from app.domain.money import format_rupiah, parse_amount
from app.domain.periods import month_label, month_window, period_window, shift_date, week_window


class TestParseAmount:
    def test_plain(self):
        assert parse_amount("25000") == Decimal("25000")

    def test_thousands_dot(self):
        assert parse_amount("25.000") == Decimal("25000")
        assert parse_amount("1.500.000") == Decimal("1500000")

    def test_decimal_comma(self):
        assert parse_amount("2,5jt") == Decimal("2500000")
        assert parse_amount("1,5jt") == Decimal("1500000")

    def test_suffixes(self):
        assert parse_amount("25rb") == Decimal("25000")
        assert parse_amount("25 ribu") == Decimal("25000")
        assert parse_amount("5k") == Decimal("5000")
        assert parse_amount("2jt") == Decimal("2000000")
        assert parse_amount("2 juta") == Decimal("2000000")

    def test_spaces(self):
        assert parse_amount(" 25 rb ") == Decimal("25000")

    def test_invalid(self):
        assert parse_amount("") is None
        assert parse_amount("abc") is None
        assert parse_amount("10usd") is None
        assert parse_amount("-5") is None
        assert parse_amount(None) is None

    def test_zero(self):
        assert parse_amount("0") is None
        assert parse_amount("0", allow_zero=True) == Decimal("0")


class TestFormatRupiah:
    def test_basic(self):
        assert format_rupiah(Decimal("1234567")) == "Rp 1.234.567"

    def test_decimal(self):
        assert format_rupiah(Decimal("1234567.5")) == "Rp 1.234.567,5"

    def test_negative(self):
        assert format_rupiah(Decimal("-50000")) == "-Rp 50.000"

    def test_zero(self):
        assert format_rupiah(Decimal("0")) == "Rp 0"


class TestPeriods:
    def test_month_window(self):
        assert month_window(date(2026, 8, 16)) == (date(2026, 8, 1), date(2026, 8, 31))

    def test_month_window_december(self):
        assert month_window(date(2026, 12, 5)) == (date(2026, 12, 1), date(2026, 12, 31))

    def test_week_window(self):
        # 2026-08-12 adalah Rabu
        assert week_window(date(2026, 8, 12)) == (date(2026, 8, 10), date(2026, 8, 16))

    def test_period_window_vocabularies(self):
        d = date(2026, 8, 16)
        assert period_window("weekly", d) == week_window(d)
        assert period_window("monthly", d) == month_window(d)
        assert period_window("day", d) == (d, d)
        assert period_window("daily", d) == (d, d)

    def test_shift_date(self):
        assert shift_date("day", date(2026, 8, 16), -1) == date(2026, 8, 15)
        assert shift_date("month", date(2026, 8, 16), -1) == date(2026, 7, 1)
        assert shift_date("month", date(2026, 1, 16), -1) == date(2025, 12, 1)

    def test_month_label(self):
        assert month_label(date(2026, 8, 1)) == "2026-08"


class TestLogic:
    def test_compute_balance(self):
        bal = compute_balance(
            Decimal("100000"), Decimal("50000"), Decimal("30000"),
            Decimal("20000"), Decimal("5000"),
        )
        assert bal == Decimal("105000")

    def test_budget_alert_warn_crossing(self):
        # 0 → 80% menyentuh threshold
        assert budget_alert(Decimal("0"), Decimal("800000"), Decimal("1000000"), 80) == "warn"

    def test_budget_alert_over_crossing(self):
        assert budget_alert(Decimal("950000"), Decimal("1050000"), Decimal("1000000"), 80) == "over"

    def test_budget_alert_both(self):
        # 70% → 105% : menyentuh 80 DAN 100 sekaligus — "over" lebih penting
        assert budget_alert(Decimal("700000"), Decimal("1050000"), Decimal("1000000"), 80) == "over"

    def test_budget_alert_none(self):
        assert budget_alert(Decimal("300000"), Decimal("500000"), Decimal("1000000"), 80) is None
        assert budget_alert(Decimal("0"), Decimal("100000"), Decimal("0"), 80) is None

    def test_freemium_disabled(self):
        user = SimpleNamespace(is_premium=False, free_transaction_count=999)
        allowed, _ = can_add_transaction(user, False, 200)
        assert allowed

    def test_freemium_premium_always(self):
        user = SimpleNamespace(is_premium=True, free_transaction_count=999)
        allowed, _ = can_add_transaction(user, True, 200)
        assert allowed

    def test_freemium_under_limit(self):
        user = SimpleNamespace(is_premium=False, free_transaction_count=199)
        allowed, _ = can_add_transaction(user, True, 200)
        assert allowed

    def test_freemium_blocked(self):
        user = SimpleNamespace(is_premium=False, free_transaction_count=200)
        allowed, msg = can_add_transaction(user, True, 200)
        assert not allowed
        assert msg
