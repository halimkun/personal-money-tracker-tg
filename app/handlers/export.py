"""Export riwayat ke CSV (PRD §5.1)."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.db.models import User
from app.services.export import build_csv
from app.utils.format import today_local

router = Router()


@router.message(Command("export"))
async def cmd_export(message: Message, session, user: User):
    csv_text = await build_csv(session, user.id)
    if len(csv_text.splitlines()) <= 1:  # hanya baris header
        await message.answer("Belum ada data untuk di-export.")
        return
    filename = f"moneybot_{user.telegram_id}_{today_local().isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_text.encode("utf-8-sig"), filename=filename),
        caption="📤 Export riwayat (CSV) — bisa dibuka di Excel/Google Sheets. "
                "Kolom Tanggal, Tipe, Kategori, Wallet, Jumlah, Biaya, Catatan, Sumber.",
    )
