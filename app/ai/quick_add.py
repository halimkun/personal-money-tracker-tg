"""Quick-add via AI (PRD §5.1b): parsing teks bebas / foto struk → draft terstruktur.

Output AI hanyalah *tebakan* — user WAJIB konfirmasi lewat kartu (handlers.quick_add).
Kalau AI menilai bukan transaksi / ragu → action "unclear", bot tidak memaksakan.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client
from app.config import settings as app_settings
from app.db.models import Category, Wallet
from app.repositories.categories import CategoryRepo
from app.repositories.wallets import WalletRepo

SYSTEM_PROMPT = """Kamu adalah parser keuangan untuk bot pencatatan keuangan pribadi.
Tugasmu: menganalisis pesan pengguna dan menentukan apakah itu transaksi keuangan, transfer antar wallet, atau bukan transaksi.

PENTING: Jangan menebak transaksi kalau pesannya BUKAN tentang keuangan (sapaan, pertanyaan, curhat, dll). Dalam kasus itu set "action" = "unclear".

Output HARUS berupa objek JSON dengan skema persis:
{
  "action": "transaction" | "transfer" | "multi" | "unclear",
  "type": "income" | "expense",
  "amount": 25000,
  "category_guess": "Makan & Minum",
  "wallet_guess": "Cash",
  "from_wallet_guess": "Cash",
  "to_wallet_guess": "GoPay",
  "note": "beli kopi di Indomaret",
  "date": "2026-08-16",
  "items": [
    {"type": "expense", "amount": 25000, "category_guess": "Makan & Minum",
     "wallet_guess": "", "note": "2 kopi kenangan", "date": "2026-08-16"}
  ],
  "confidence": "high" | "low"
}

Aturan:
- "transaction" = uang masuk/keluar; "transfer" = uang hanya pindah antar wallet (kata kunci: transfer, pindah, move). Untuk transfer isi from_wallet_guess & to_wallet_guess.
- "multi" = pesan berisi LEBIH DARI SATU transaksi terpisah (baris terpisah / beda merchant / daftar belanja). Isi "items" dengan SATU objek per transaksi (field per item: type, amount, category_guess, wallet_guess, note, date — aturan sama seperti transaksi tunggal). Field utama (type/amount/note/dst.) kosongkan (null/""). Keterangan waktu di luar daftar (mis. "kemarin" di baris pertama) berlaku untuk SEMUA item. Jangan pecah SATU transaksi jadi dua — "beli kopi dan roti 30rb" tetap SATU transaksi dengan note.
- amount: angka Rupiah tanpa titik/koma. Pahami singkatan: 25rb = 25000, 2jt = 2000000, 5k = 5000.
- Kalau ada beberapa angka (mis. "kopi kenangan 2 50000"): angka TERAKHIR adalah total transaksi; angka sebelumnya = jumlah barang, catat di note.
- date: tanggal transaksi dalam format YYYY-MM-DD kalau user menyebut keterangan waktu. Hitung relatif terhadap "Waktu sekarang" yang diberikan di system prompt: kemarin = hari ini - 1 hari, besok = hari ini + 1, lusa = +2, "2 hari lalu" = -2, "minggu lalu" = -7, tanggal/bulan disebut ("17 agustus") = tanggal itu di tahun yang sama. Kalau TIDAK ada keterangan waktu sama sekali → "date": "". Keterangan waktu BUKAN alasan confidence "low" dan TIDAK perlu dimasukkan ke note.
- category_guess: pilih nama kategori PALING sesuai dari daftar yang diberikan. Kalau tidak ada yang cocok gunakan "Lainnya".
- wallet_guess / from_wallet_guess / to_wallet_guess: nama wallet dari daftar. Kosongkan ("") kalau tidak disebut.
- confidence: "low" HANYA kalau nominal tidak jelas/tidak ada angka sama sekali. Pesan dengan nominal jelas dan konteks transaksi jelas → "high", meskipun ada keterangan waktu atau jumlah barang.
- note: deskripsi singkat Bahasa Indonesia maks 100 karakter, boleh kosong.
- Untuk foto struk: baca nominal TOTAL, tanggal struk & nama merchant dari struk.

Contoh pesan → jawaban benar (asumsi "Waktu sekarang" = 2026-08-17 06:30):
1. "beli kopi 25rb" → {"action": "transaction", "type": "expense", "amount": 25000, "category_guess": "Makan & Minum", "wallet_guess": "", "from_wallet_guess": "", "to_wallet_guess": "", "note": "beli kopi", "date": "", "confidence": "high"}
2. "kopi kenangan 2 50000 kemarin" → {"action": "transaction", "type": "expense", "amount": 50000, "category_guess": "Makan & Minum", "wallet_guess": "", "from_wallet_guess": "", "to_wallet_guess": "", "note": "2 kopi kenangan", "date": "2026-08-16", "confidence": "high"}
3. "gajian 5jt" → {"action": "transaction", "type": "income", "amount": 5000000, "category_guess": "Gaji", "wallet_guess": "", "from_wallet_guess": "", "to_wallet_guess": "", "note": "gajian", "date": "", "confidence": "high"}
4. "transfer 100rb ke gopay" → {"action": "transfer", "type": null, "amount": 100000, "category_guess": "", "wallet_guess": "", "from_wallet_guess": "", "to_wallet_guess": "GoPay", "note": "transfer ke gopay", "date": "", "confidence": "high"}
5. "halo" → {"action": "unclear", "type": null, "amount": null, "category_guess": "", "wallet_guess": "", "from_wallet_guess": "", "to_wallet_guess": "", "note": "", "date": "", "confidence": "low"}
6. "kemarin
kopi kenangan 2 50000
KFC 2 60000" → {"action": "multi", "type": null, "amount": null, "category_guess": "", "wallet_guess": "", "from_wallet_guess": "", "to_wallet_guess": "", "note": "", "date": "", "items": [{"type": "expense", "amount": 50000, "category_guess": "Makan & Minum", "wallet_guess": "", "note": "2 kopi kenangan", "date": "2026-08-16"}, {"type": "expense", "amount": 60000, "category_guess": "Makan & Minum", "wallet_guess": "", "note": "2 KFC", "date": "2026-08-16"}], "confidence": "high"}"""


def _system_prompt() -> str:
    """System prompt + konteks waktu saat ini (untuk hitung tanggal relatif)."""
    now = datetime.now(app_settings.tz)
    return SYSTEM_PROMPT + f"\n\nWaktu sekarang: {now:%Y-%m-%d %H:%M} ({app_settings.tz})."


@dataclass
class QuickAddResult:
    action: str  # transaction | transfer | multi | unclear
    type: str | None
    amount: Decimal | None
    category_guess: str | None
    wallet_guess: str | None
    from_wallet_guess: str | None
    to_wallet_guess: str | None
    note: str | None
    date_iso: str | None  # YYYY-MM-DD, None kalau tidak disebut
    confidence: str | None
    items: list["QuickAddResult"] | None = None  # untuk action "multi"

    @property
    def is_unclear(self) -> bool:
        if self.action == "multi":
            return not self.items
        if self.action not in ("transaction", "transfer") or self.confidence == "low":
            return True
        if self.amount is None:
            return True
        if self.action == "transaction" and self.type is None:
            return True
        return False


async def build_context(session: AsyncSession, user_id: int) -> str:
    """Daftar kategori & wallet milik user sebagai context untuk AI (PRD §5.1b)."""
    categories = await CategoryRepo(session).list_for_user(user_id)
    wallets = await WalletRepo(session).list_by_user(user_id, active_only=True)

    lines = ["Daftar kategori:"]
    for t, label in (("expense", "Pengeluaran"), ("income", "Pemasukan")):
        cats = [c for c in categories if c.type == t]
        names = [f"{c.name}" + (f" (keywords: {', '.join(c.keywords)})" if c.keywords else "") for c in cats]
        lines.append(f"- {label}: {'; '.join(names)}")
    lines.append("")
    wallet_names = ", ".join(w.name for w in wallets) or "(belum ada)"
    lines.append(f"Daftar wallet: {wallet_names}")
    return "\n".join(lines)


def _parse_date(raw) -> str | None:
    """Validasi tanggal AI → 'YYYY-MM-DD' atau None kalau tidak valid/kosong."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _parse_flat(data: dict) -> QuickAddResult:
    """Parsing satu objek (transaksi tunggal / satu item)."""
    action = str(data.get("action", "unclear")).strip().lower()
    type_ = str(data.get("type") or "").strip().lower()
    if type_ not in ("income", "expense"):
        type_ = None
    try:
        amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
        if amount <= 0:
            amount = None
    except (InvalidOperation, ValueError, TypeError):
        amount = None
    return QuickAddResult(
        action=action,
        type=type_,
        amount=amount,
        category_guess=(data.get("category_guess") or "").strip() or None,
        wallet_guess=(data.get("wallet_guess") or "").strip() or None,
        from_wallet_guess=(data.get("from_wallet_guess") or "").strip() or None,
        to_wallet_guess=(data.get("to_wallet_guess") or "").strip() or None,
        note=(str(data.get("note") or "").strip()[:200] or None),
        date_iso=_parse_date(data.get("date")),
        confidence=str(data.get("confidence") or "low").strip().lower(),
    )


async def _parse_result(data: dict) -> QuickAddResult:
    result = _parse_flat(data)
    if result.action == "multi":
        items = [_parse_flat({**it, "action": "transaction"})
                 for it in (data.get("items") or []) if isinstance(it, dict)]
        valid = [it for it in items if it.type and it.amount]
        if not valid:
            result.action = "unclear"  # tidak ada item yang valid → tolak
        else:
            result.items = valid
    return result


async def parse_text(session: AsyncSession, user_id: int, text: str) -> QuickAddResult:
    context = await build_context(session, user_id)
    data = await client.complete_json(
        session,
        [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": f"{context}\n\nPesan user: {text}"},
        ],
    )
    return await _parse_result(data)


async def parse_image(session: AsyncSession, user_id: int, image_b64: str) -> QuickAddResult:
    context = await build_context(session, user_id)
    data = await client.complete_json(
        session,
        [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{context}\n\nFoto struk/nota di atas. Analisis isinya."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
    )
    return await _parse_result(data)


def _match_name(name: str, guess: str) -> bool:
    return guess and (name.lower() == guess.lower() or name.lower() in guess.lower() or guess.lower() in name.lower())


async def resolve_category(session: AsyncSession, user_id: int, guess: str | None, type_: str) -> Category:
    """Cocokkan tebakan kategori AI → kategori user/global. Fallback: 'Lainnya'.'"""
    repo = CategoryRepo(session)
    categories = [c for c in await repo.list_for_user(user_id) if c.type == type_]
    if guess:
        for c in categories:
            if _match_name(c.name, guess):
                return c
        for c in categories:
            for kw in c.keywords or []:
                if kw.lower() in guess.lower():
                    return c
    fallback = await repo.get_global_fallback(type_)
    if fallback:
        return fallback
    # jaga-jaga kalau seed belum jalan
    return await repo.create(None, "Lainnya", type_, "📦", [])


async def resolve_wallet(session: AsyncSession, user_id: int, guess: str | None) -> Wallet | None:
    """Cocokkan tebakan wallet → wallet user. Fallback: wallet default."""
    wallets = await WalletRepo(session).list_by_user(user_id, active_only=True)
    if not wallets:
        return None
    if guess:
        for w in wallets:
            if _match_name(w.name, guess):
                return w
    for w in wallets:
        if w.is_default:
            return w
    return wallets[0]
