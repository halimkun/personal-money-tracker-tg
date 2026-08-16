"""Export riwayat ke CSV (PRD §5.1 nice-to-have) — transaksi + transfer."""

import csv
from io import StringIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction, WalletTransfer
from app.domain.money import format_rupiah
from app.repositories.categories import CategoryRepo
from app.repositories.transactions import TransactionRepo
from app.repositories.transfers import TransferRepo
from app.repositories.wallets import WalletRepo
from app.utils.format import fmt_date

HEADERS = ["Tanggal", "Tipe", "Kategori", "Wallet", "Jumlah", "Biaya", "Catatan", "Sumber"]

SOURCE_LABELS = {"manual": "Manual", "ai_text": "AI teks", "ai_image": "AI foto"}


async def build_csv(session: AsyncSession, user_id: int) -> str:
    tx_repo = TransactionRepo(session)
    tr_repo = TransferRepo(session)
    categories = {c.id: c.name for c in await CategoryRepo(session).list_for_user(user_id)}
    wallets = {w.id: w.name for w in await WalletRepo(session).list_by_user(user_id, active_only=False)}

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)

    transactions = await tx_repo.list_for_export(user_id)
    transfers = await tr_repo.list_for_export(user_id)

    rows: list[tuple] = []
    for tx in transactions:
        rows.append((
            tx.occurred_at,
            "Pemasukan" if tx.type == "income" else "Pengeluaran",
            categories.get(tx.category_id, "?"),
            wallets.get(tx.wallet_id, "?"),
            tx.amount,
            "",
            tx.note or "",
            SOURCE_LABELS.get(tx.source, tx.source),
        ))
    for tr, from_name, to_name in transfers:
        rows.append((
            tr.occurred_at,
            "Transfer",
            "",
            f"{from_name} → {to_name}",
            tr.amount,
            tr.fee if tr.fee else "",
            tr.note or "",
            "Manual",
        ))

    rows.sort(key=lambda r: r[0], reverse=True)
    for r in rows:
        writer.writerow([
            fmt_date(r[0]), r[1], r[2], r[3],
            format_rupiah(r[4]), format_rupiah(r[5]) if r[5] else "", r[6], r[7],
        ])
    return buf.getvalue()
