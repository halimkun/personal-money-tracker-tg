"""Generator insight bulanan (PRD §5.4).

Hanya angka AGREGAT yang dikirim ke AI (bukan raw data transaksi) — demi efisiensi & privasi.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client
from app.domain.money import format_rupiah

SYSTEM_PROMPT = """Kamu adalah asisten analis keuangan pribadi yang ramah, berbicara Bahasa Indonesia santai.
Buat insight berdasarkan data agregat yang diberikan. Maksimal 250 kata.
Struktur output:
1. 📊 Ringkasan singkat (pemasukan, pengeluaran, net)
2. 🔍 Temuan menarik / pola pengeluaran
3. 💡 Saran singkat yang actionable

Gunakan emoji secukupnya. Jangan mengarang data yang tidak diberikan."""


async def generate(session: AsyncSession, user_id: int, agg: dict) -> str:
    """Generate insight dari agregat bulanan."""
    cat_lines = "\n".join(
        f"- {c['icon']} {c['name']}: {format_rupiah(c['total'])} ({c['pct']:.0f}%)"
        for c in agg["by_category"][:5]
    ) or "- (tidak ada pengeluaran)"

    prev = agg["prev_month_label"]
    user_msg = f"""Data keuangan bulan {agg['month_label']}:
- Total pemasukan: {format_rupiah(agg['income'])}
- Total pengeluaran: {format_rupiah(agg['expense'])}
- Net: {format_rupiah(agg['net'])}
- Jumlah transaksi: {agg['tx_count']}

Pengeluaran terbesar per kategori:
{cat_lines}

Perbandingan dengan bulan sebelumnya ({prev}):
- Pemasukan bulan lalu: {format_rupiah(agg['prev_income'])}
- Pengeluaran bulan lalu: {format_rupiah(agg['prev_expense'])}"""

    return await client.complete_text(
        session,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
