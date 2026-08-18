"""Fix FK admin_logs.admin_id & payments.approved_by → users.telegram_id.

Kedua kolom menyimpan telegram_id admin (dipakai untuk perbandingan dengan
settings.admin_set), tapi FK-nya menunjuk users.id (surrogate autoincrement).
Bug ini tak terlihat di SQLite dev (FK tidak ditegakkan), langsung error di
PostgreSQL: insert/update violates foreign key constraint.

revision = "0002"
down_revision = "0001"
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _sqlite_rebuild(bind, table: str, column: str, target: str) -> None:
    """Rebuild tabel SQLite tanpa FK lama di kolom `column` (FK SQLite tidak
    bernama sehingga tak bisa di-drop batch secara langsung), lalu pasang FK
    baru ke users.<target>. Data ikut tercopy otomatis oleh batch mode."""
    metadata = sa.MetaData()
    reflected = sa.Table(table, metadata, autoload_with=bind)
    for col in reflected.columns:
        for fk in list(col.foreign_keys):
            if col.name == column:  # buang FK lama apa pun targetnya
                col.foreign_keys.remove(fk)
    for constraint in list(reflected.constraints):
        if isinstance(constraint, sa.ForeignKeyConstraint) and column in constraint.columns:
            reflected.constraints.remove(constraint)
    with op.batch_alter_table(table, copy_from=reflected) as batch:
        batch.create_foreign_key(
            f"fk_{table}_{column}_{target}", "users", [column], [target]
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite_rebuild(bind, "admin_logs", "admin_id", "telegram_id")
        _sqlite_rebuild(bind, "payments", "approved_by", "telegram_id")
    else:
        op.drop_constraint("admin_logs_admin_id_fkey", "admin_logs", type_="foreignkey")
        op.create_foreign_key("admin_logs_admin_id_fkey", "admin_logs", "users",
                              ["admin_id"], ["telegram_id"])
        op.drop_constraint("payments_approved_by_fkey", "payments", type_="foreignkey")
        op.create_foreign_key("payments_approved_by_fkey", "payments", "users",
                              ["approved_by"], ["telegram_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite_rebuild(bind, "admin_logs", "admin_id", "id")
        _sqlite_rebuild(bind, "payments", "approved_by", "id")
    else:
        op.drop_constraint("admin_logs_admin_id_fkey", "admin_logs", type_="foreignkey")
        op.create_foreign_key("admin_logs_admin_id_fkey", "admin_logs", "users",
                              ["admin_id"], ["id"])
        op.drop_constraint("payments_approved_by_fkey", "payments", type_="foreignkey")
        op.create_foreign_key("payments_approved_by_fkey", "payments", "users",
                              ["approved_by"], ["id"])
