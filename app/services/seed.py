"""Seed data awal: kategori global (user_id NULL) — idempotent."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.categories import CategoryRepo

_DEFAULT_CATEGORIES: list[dict] = [
    # Pengeluaran
    {"type": "expense", "name": "Makan & Minum", "icon": "🍜",
     "keywords": ["makan", "kopi", "gofood", "grabfood", "warteg", "restoran", "sarapan",
                  "makan siang", "makan malam", "jajan", "snack", "ngopi", "cafe", "minum"]},
    {"type": "expense", "name": "Transportasi", "icon": "🚗",
     "keywords": ["ojek", "gojek", "grab", "bensin", "parkir", "tol", "kereta", "bus",
                  "transport", "ojol", "bbm"]},
    {"type": "expense", "name": "Belanja", "icon": "🛒",
     "keywords": ["belanja", "minimarket", "indomaret", "alfamart", "supermarket", "toko",
                  "beli", "shopee", "tokopedia", "lazada", "mall", "marketplace", "online"]},
    {"type": "expense", "name": "Tagihan", "icon": "🧾",
     "keywords": ["listrik", "air", "internet", "wifi", "pulsa", "paket data", "sewa",
                  "tagihan", "iuran", "cicilan", "kredit", "pln"]},
    {"type": "expense", "name": "Hiburan", "icon": "🎬",
     "keywords": ["bioskop", "nonton", "game", "steam", "spotify", "netflix", "jalan",
                  "liburan", "travel", "entertainment", "konser"]},
    {"type": "expense", "name": "Kesehatan", "icon": "💊",
     "keywords": ["obat", "dokter", "rumah sakit", "apotek", "klinik", "vitamin", "cek up"]},
    {"type": "expense", "name": "Pendidikan", "icon": "📚",
     "keywords": ["buku", "kursus", "sekolah", "kuliah", "bootcamp", "belajar", "training"]},
    {"type": "expense", "name": "Lainnya", "icon": "📦", "keywords": []},
    # Pemasukan
    {"type": "income", "name": "Gaji", "icon": "💰",
     "keywords": ["gaji", "salary", "upah", "honor", "freelance"]},
    {"type": "income", "name": "Bonus", "icon": "🎁",
     "keywords": ["bonus", "thr", "tunjangan"]},
    {"type": "income", "name": "Investasi", "icon": "📈",
     "keywords": ["investasi", "saham", "reksadana", "dividen", "crypto", "deposito", "bunga"]},
    {"type": "income", "name": "Penjualan", "icon": "🏷️",
     "keywords": ["jual", "penjualan", "jualan"]},
    {"type": "income", "name": "Lainnya", "icon": "📦", "keywords": []},
]


async def seed_global_categories(session: AsyncSession) -> None:
    repo = CategoryRepo(session)
    if await repo.global_count() > 0:
        return
    for c in _DEFAULT_CATEGORIES:
        await repo.create(None, c["name"], c["type"], c["icon"], c["keywords"])
    await session.flush()
