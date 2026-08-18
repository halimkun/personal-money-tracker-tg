"""Test service layer dengan SQLite in-memory — orkestrasi bisnis end-to-end."""

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import User
from app.services.budgets import BudgetService
from app.services.errors import FreemiumBlockedError, ValidationError
from app.services.seed import seed_global_categories
from app.services.settings import SettingsService
from app.services.summary import SummaryService
from app.services.transactions import TransactionService
from app.services.transfers import TransferService
from app.services.wallets import WalletService
from tests.conftest import make_category, make_tx, make_user, make_wallet

D = date(2026, 8, 10)


class TestReportHelpers:
    async def test_available_months(self, session):
        from app.repositories.transactions import TransactionRepo

        user = await make_user(session)
        w = await make_wallet(session, user.id)
        c = await make_category(session, None)
        await make_tx(session, user.id, w.id, c.id, occurred_at=date(2026, 8, 10))
        await make_tx(session, user.id, w.id, c.id, occurred_at=date(2026, 5, 2))
        await make_tx(session, user.id, w.id, c.id, occurred_at=date(2026, 5, 20))
        await make_tx(session, user.id, w.id, c.id, occurred_at=date(2024, 6, 20))
        months = await TransactionRepo(session).available_months(user.id)
        assert months == [(2026, 8), (2026, 5), (2024, 6)]  # unik + terbaru dulu

    async def test_available_months_empty(self, session):
        from app.repositories.transactions import TransactionRepo

        user = await make_user(session)
        assert await TransactionRepo(session).available_months(user.id) == []


class TestAdminFks:
    """Regresi: admin_logs.admin_id & payments.approved_by menyimpan
    telegram_id, jadi FK-nya harus menunjuk users.telegram_id (bukan
    users.id). SQLite dev tidak menegakkan FK — PostgreSQL menegakkan."""

    def test_fk_targets_telegram_id(self):
        from app.db.models import AdminLog, Payment

        for table in (AdminLog.__table__, Payment.__table__):
            column = "admin_id" if table.name == "admin_logs" else "approved_by"
            fks = list(table.c[column].foreign_keys)
            assert len(fks) == 1
            target = next(iter(fks)).column
            assert (target.table.name, target.name) == ("users", "telegram_id")

    async def test_settings_set_logs_by_telegram_id(self, session):
        from sqlalchemy import select

        from app.db.models import AdminLog

        user = await make_user(session, tg_id=444060895)
        await SettingsService(session).set("payment_required", "true",
                                           admin_id=user.telegram_id)
        rows = (await session.execute(select(AdminLog))).scalars().all()
        assert len(rows) == 1
        assert rows[0].admin_id == user.telegram_id  # bukan surrogate user.id

    def test_available_months_sql_portable(self):
        """Query bulan spesifik harus terkompilasi di SQLite DAN PostgreSQL
        (regresi: strftime tidak ada di PostgreSQL)."""
        from sqlalchemy.dialects import postgresql, sqlite

        from app.repositories.transactions import _available_months_stmt

        stmt = _available_months_stmt(1)

        pg_sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "strftime" not in pg_sql.lower()
        assert "extract" in pg_sql.lower()

        sqlite_sql = str(stmt.compile(dialect=sqlite.dialect()))
        assert "extract" not in sqlite_sql.lower()  # dikompilasi jadi strftime
        assert "strftime" in sqlite_sql.lower()

    async def test_build_range_summary(self, session):
        user = await make_user(session)
        w = await make_wallet(session, user.id)
        c = await make_category(session, None)
        await make_tx(session, user.id, w.id, c.id, amount="10000",
                      occurred_at=date(2026, 8, 1))
        await make_tx(session, user.id, w.id, c.id, type_="income", amount="20000",
                      occurred_at=date(2026, 7, 15))
        await make_tx(session, user.id, w.id, c.id, amount="5000",
                      occurred_at=date(2026, 6, 30))
        data = await SummaryService(session).build_range_summary(
            user.id, date(2026, 7, 1), date(2026, 8, 31)
        )
        assert data["start"] == date(2026, 7, 1)
        assert data["end"] == date(2026, 8, 31)
        assert data["income"] == Decimal("20000")
        assert data["expense"] == Decimal("10000")  # tx Juni di luar jendela
        assert data["tx_count"] == 2


class TestWalletBalance:
    async def test_balance_on_the_fly(self, session):
        """Saldo = initial + income − expense − transfer_out + transfer_in."""
        user = await make_user(session)
        w_cash = await make_wallet(session, user.id, name="Cash", initial="100000")
        w_bank = await make_wallet(session, user.id, name="BCA", initial="0", is_default=False)
        cat = await make_category(session, None, name="Lainnya")

        await make_tx(session, user.id, w_cash.id, cat.id, type_="income", amount="100000")
        await make_tx(session, user.id, w_cash.id, cat.id, type_="expense", amount="30000")

        from app.db.models import WalletTransfer
        from datetime import datetime

        session.add(WalletTransfer(
            user_id=user.id, from_wallet_id=w_cash.id, to_wallet_id=w_bank.id,
            amount=Decimal("20000"), fee=Decimal("0"), occurred_at=D,
            created_at=datetime(2026, 8, 10),
        ))
        session.add(WalletTransfer(
            user_id=user.id, from_wallet_id=w_bank.id, to_wallet_id=w_cash.id,
            amount=Decimal("5000"), fee=Decimal("0"), occurred_at=D,
            created_at=datetime(2026, 8, 10),
        ))
        await session.flush()

        svc = WalletService(session)
        assert await svc.balance(w_cash.id) == Decimal("155000")
        assert await svc.balance(w_bank.id) == Decimal("15000")

    async def test_first_wallet_default(self, session):
        user = await make_user(session)
        w1 = await WalletService(session).create(user.id, "Cash", "cash", Decimal("0"))
        assert w1.is_default
        w2 = await WalletService(session).create(user.id, "BCA", "bank", Decimal("0"))
        assert not w2.is_default

    async def test_deactivate_blocks_last_active(self, session):
        user = await make_user(session)
        w = await make_wallet(session, user.id)
        with pytest.raises(ValidationError):
            await WalletService(session).deactivate(user.id, w.id)


class TestFreemium:
    async def _setup(self, session, *, limit: int = 1):
        user = await make_user(session)
        await make_wallet(session, user.id)
        await seed_global_categories(session)
        settings_svc = SettingsService(session)
        await settings_svc.set("payment_required", "true")
        await settings_svc.set("free_transaction_limit", str(limit))
        return user

    async def _categories(self, session, user_id):
        from app.repositories.categories import CategoryRepo
        return await CategoryRepo(session).list_for_user(user_id)

    async def test_free_limit_counts_and_blocks(self, session):
        user = await self._setup(session, limit=1)
        cats = await self._categories(session, user.id)
        expense = next(c for c in cats if c.type == "expense")
        wallets = await WalletRepo_all(session, user.id)

        await TransactionService(session).create(
            user, type_="expense", amount=Decimal("10000"),
            category_id=expense.id, wallet_id=wallets[0].id, occurred_at=D,
        )
        assert user.free_transaction_count == 1
        with pytest.raises(FreemiumBlockedError):
            await TransactionService(session).create(
                user, type_="expense", amount=Decimal("5000"),
                category_id=expense.id, wallet_id=wallets[0].id, occurred_at=D,
            )

    async def test_premium_not_counted(self, session):
        user = await make_user(session, is_premium=True)
        await make_wallet(session, user.id)
        await seed_global_categories(session)
        settings_svc = SettingsService(session)
        await settings_svc.set("payment_required", "true")
        await settings_svc.set("free_transaction_limit", "1")
        cats = await self._categories(session, user.id)
        expense = next(c for c in cats if c.type == "expense")
        wallets = await WalletRepo_all(session, user.id)

        for _ in range(3):
            await TransactionService(session).create(
                user, type_="expense", amount=Decimal("10000"),
                category_id=expense.id, wallet_id=wallets[0].id, occurred_at=D,
            )
        assert user.free_transaction_count == 0

    async def test_transfers_do_not_count(self, session):
        user = await self._setup(session, limit=1)
        w1 = await make_wallet(session, user.id, name="A", initial="100000")
        w2 = await make_wallet(session, user.id, name="B", is_default=False)
        await TransferService(session).create(
            user, from_wallet_id=w1.id, to_wallet_id=w2.id,
            amount=Decimal("10000"), occurred_at=D,
        )
        assert user.free_transaction_count == 0


async def WalletRepo_all(session, user_id):
    from app.repositories.wallets import WalletRepo
    return await WalletRepo(session).list_by_user(user_id, active_only=True)


class TestBudgetAlerts:
    async def test_crossing_alerts_only(self, session):
        """Alert muncul HANYA saat menyentuh threshold/melewati batas — tidak spam."""
        user = await make_user(session)
        wallet = await make_wallet(session, user.id)
        await seed_global_categories(session)
        cat = await make_category(session, None, name="Hiburan", type_="expense")
        await BudgetService(session).create(
            user.id, category_id=cat.id, wallet_id=None,
            period_type="monthly", amount=Decimal("1000000"),
        )
        svc = TransactionService(session)

        _, alerts = await svc.create(
            user, type_="expense", amount=Decimal("800000"),
            category_id=cat.id, wallet_id=wallet.id, occurred_at=D,
        )
        assert any("80%" in a for a in alerts)  # menyentuh threshold

        _, alerts = await svc.create(
            user, type_="expense", amount=Decimal("100000"),
            category_id=cat.id, wallet_id=wallet.id, occurred_at=D,
        )
        assert alerts == []  # 80%→90% — tidak ada crossing baru

        _, alerts = await svc.create(
            user, type_="expense", amount=Decimal("100000"),
            category_id=cat.id, wallet_id=wallet.id, occurred_at=D,
        )
        assert any("terlampaui" in a for a in alerts)  # 90%→100% over

    async def test_budget_must_be_expense_category(self, session):
        user = await make_user(session)
        await make_wallet(session, user.id)
        cat = await make_category(session, None, name="Gaji", type_="income")
        with pytest.raises(ValidationError):  # budget hanya untuk kategori expense
            await BudgetService(session).create(
                user.id, category_id=cat.id, wallet_id=None,
                period_type="monthly", amount=Decimal("100000"),
            )


class TestTransfer:
    async def test_insufficient_balance(self, session):
        user = await make_user(session)
        w1 = await make_wallet(session, user.id, name="A", initial="50000")
        w2 = await make_wallet(session, user.id, name="B", is_default=False)
        with pytest.raises(ValidationError):
            await TransferService(session).create(
                user, from_wallet_id=w1.id, to_wallet_id=w2.id,
                amount=Decimal("100000"), occurred_at=D,
            )

    async def test_same_wallet_rejected(self, session):
        user = await make_user(session)
        w1 = await make_wallet(session, user.id, name="A", initial="50000")
        with pytest.raises(ValidationError):
            await TransferService(session).create(
                user, from_wallet_id=w1.id, to_wallet_id=w1.id,
                amount=Decimal("10000"), occurred_at=D,
            )


class TestSummary:
    async def test_totals_and_breakdown(self, session):
        user = await make_user(session)
        wallet = await make_wallet(session, user.id)
        cat_makan = await make_category(session, None, name="Makan", type_="expense")
        cat_belanja = await make_category(session, None, name="Belanja", type_="expense")
        cat_gaji = await make_category(session, None, name="Gaji", type_="income")

        await make_tx(session, user.id, wallet.id, cat_makan.id, amount="10000")
        await make_tx(session, user.id, wallet.id, cat_belanja.id, amount="50000")
        await make_tx(session, user.id, wallet.id, cat_gaji.id, type_="income", amount="100000")

        data = await SummaryService(session).build_summary(user.id, "month", D)
        assert data["income"] == Decimal("100000")
        assert data["expense"] == Decimal("60000")
        assert data["net"] == Decimal("40000")
        assert data["tx_count"] == 3
        assert data["by_category"][0]["name"] == "Belanja"  # terbesar dulu


class TestSeed:
    async def test_seed_idempotent(self, session):
        await seed_global_categories(session)
        await seed_global_categories(session)
        from app.repositories.categories import CategoryRepo
        assert await CategoryRepo(session).global_count() == 13  # 8 expense + 5 income
