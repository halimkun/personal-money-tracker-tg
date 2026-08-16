"""Initial schema — 11 tabel sesuai PRD §4.

Revision ID: 0001
Revises:
Create Date: 2026-08-16

Catatan portabilitas (PostgreSQL ↔ SQLite):
- JSON generik (bukan JSONB), enum sebagai String, keywords sebagai JSON.
- Datetime disimpan naive UTC.
"""

from alembic import op
import sqlalchemy as sa

# FK mengikuti tipe PK target (portabel BigIntPK dari models.py)
BigInt = sa.BigInteger().with_variant(sa.Integer, "sqlite")

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text()),
        sa.Column("full_name", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_premium", sa.Boolean(), nullable=False),
        sa.Column("premium_until", sa.DateTime()),
        sa.Column("free_transaction_count", sa.Integer(), nullable=False),
        sa.Column("ai_insight_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "wallets",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("initial_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_wallets_user_id", "wallets", ["user_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("icon", sa.String(10)),
        sa.Column("keywords", sa.JSON(), nullable=True),
    )
    op.create_index("ix_categories_user_id", "categories", ["user_id"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("wallet_id", BigInt, sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("category_id", BigInt, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("source_file_id", sa.Text()),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_wallet_id", "transactions", ["wallet_id"])

    op.create_table(
        "wallet_transfers",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("from_wallet_id", BigInt, sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("to_wallet_id", BigInt, sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("fee", sa.Numeric(14, 2), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_wallet_transfers_user_id", "wallet_transfers", ["user_id"])

    op.create_table(
        "budgets",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category_id", BigInt, sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("wallet_id", BigInt, sa.ForeignKey("wallets.id"), nullable=True),
        sa.Column("period_type", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("alert_threshold_pct", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])

    op.create_table(
        "global_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("proof_file_id", sa.Text()),
        sa.Column("approved_by", BigInt, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime()),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])

    op.create_table(
        "ai_insights",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_insights_user_id", "ai_insights", ["user_id"])

    op.create_table(
        "admin_logs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("admin_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "callback_refs",
        sa.Column("token", sa.String(12), primary_key=True),
        sa.Column("user_id", BigInt, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_callback_refs_user_id", "callback_refs", ["user_id"])


def downgrade() -> None:
    for table in (
        "callback_refs",
        "admin_logs",
        "ai_insights",
        "payments",
        "global_settings",
        "budgets",
        "wallet_transfers",
        "transactions",
        "categories",
        "wallets",
        "users",
    ):
        op.drop_table(table)
