"""Layanan kategori custom: buat dengan keyword AI & hapus aman (PRD §4, §5.4)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category
from app.repositories.categories import CategoryRepo
from app.services.errors import ValidationError


def parse_keywords(text: str) -> list[str]:
    """'kopi; ngopi, coffee' → ['kopi', 'ngopi', 'coffee'] (unik, lowercase)."""
    parts = [p.strip().lower() for p in text.replace(";", ",").split(",")]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return seen[:20]


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(
        self, user_id: int, name: str, type_: str, keywords_text: str | None
    ) -> Category:
        name = name.strip()
        if not name:
            raise ValidationError("Nama kategori tidak boleh kosong.")
        if len(name) > 100:
            raise ValidationError("Nama kategori maksimal 100 karakter.")
        if type_ not in ("income", "expense"):
            raise ValidationError("Tipe kategori tidak valid.")
        repo = CategoryRepo(self.s)
        for c in await repo.list_custom(user_id):
            if c.name.lower() == name.lower() and c.type == type_:
                raise ValidationError("Kategori dengan nama itu sudah ada.")
        keywords = parse_keywords(keywords_text or "")
        return await repo.create(user_id, name, type_, "🏷️", keywords)

    async def delete(self, user_id: int, category_id: int) -> None:
        repo = CategoryRepo(self.s)
        category = await repo.get(category_id)
        if not category or category.user_id != user_id:
            raise ValidationError("Kategori tidak ditemukan (kategori global tidak bisa dihapus).")
        usage = await repo.count_usage(category_id)
        if usage > 0:
            raise ValidationError(
                f"Kategori ini dipakai {usage} transaksi. Hapus/edit transaksinya dulu ya."
            )
        await repo.delete(category)
