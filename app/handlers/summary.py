"""Laporan ringkasan harian/mingguan/bulanan + laporan rentang & bulan spesifik.

Menu 3 level (semua update di tempat — pola info/view):
  1. /ringkasan (toggle Hari/Minggu/Bulan + tombol 📊 Laporan)
  2. Laporan → pilih jenis: 📆 Rentang Waktu | 🗓️ Pilih Bulan Spesifik
  3a. Rentang → 1 / 3 / 6 / 12 bulan terakhir
  3b. Spesifik → pilih tahun → pilih bulan (hanya yang punya data transaksi)
"""

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.domain.money import format_rupiah
from app.domain.periods import month_window, shift_date
from app.repositories.transactions import TransactionRepo
from app.services.summary import SummaryService, pct_delta
from app.utils.format import fmt_date_ctx, today_local
from app.utils.messages import edit_or_send

router = Router()

PERIODS = {"sum:d": "day", "sum:w": "week", "sum:m": "month"}
PERIOD_NAMES = {"day": "Hari Ini", "week": "Minggu Ini", "month": "Bulan Ini"}
MONTHS_FULL = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


async def _render_report(bot, chat_id: int, message_id: int | None, data: dict,
                         title: str, kb) -> None:
    """Render satu laporan (data dari build_summary / build_range_summary)."""
    if data["tx_count"] == 0:
        text = (
            f"📊 <b>{title}</b>\n\n"
            "Belum ada transaksi di periode ini.\n"
            "Mulai catat: /catat atau ketik bebas seperti <i>beli kopi 25rb</i>"
        )
    else:
        lines = [f"📊 <b>{title}</b>"]
        if data["start"] != data["end"]:
            lines.append(f"{fmt_date_ctx(data['start'])} – {fmt_date_ctx(data['end'])}")
        net_icon = "🟢" if data["net"] >= 0 else "🔴"
        lines += [
            "",
            f"💰 Pemasukan: <b>{format_rupiah(data['income'])}</b>",
            f"💸 Pengeluaran: <b>{format_rupiah(data['expense'])}</b>",
            f"{net_icon} Selisih: <b>{format_rupiah(data['net'])}</b>",
            f"🧾 {data['tx_count']} transaksi",
        ]
        if data["by_category"]:
            lines += ["", "🏷️ <b>Pengeluaran per Kategori</b>"]
            for item in data["by_category"]:
                lines.append(f"{item['icon'] or '•'} {item['name']}: {format_rupiah(item['total'])}")
        if data["prev_expense"]:
            delta = pct_delta(data["expense"], data["prev_expense"])
            if delta:
                up = data["expense"] >= data["prev_expense"]
                arrow = "📈" if up else "📉"
                lines.append(f"\n{arrow} vs periode sebelumnya: {delta}")
        text = "\n".join(lines)

    await edit_or_send(bot, chat_id, message_id, text, kb)


async def _render(bot, chat_id: int, message_id: int | None, session, user: User,
                  period_type: str):
    """Level 1: toggle periode berjalan + pintu masuk menu laporan."""
    data = await SummaryService(session).build_summary(user.id, period_type, today_local())
    from app.keyboards.inline import ikb
    marks = {ptype: ("✅ " if ptype == period_type else "") for ptype in PERIODS.values()}
    kb = ikb([
        [
            (f"{marks['day']}📅 Hari", "sum:d"),
            (f"{marks['week']}📆 Minggu", "sum:w"),
            (f"{marks['month']}🗓️ Bulan", "sum:m"),
        ],
        [("📊 Laporan", "rep:menu")],
    ])
    await _render_report(bot, chat_id, message_id, data, PERIOD_NAMES[period_type], kb)


@router.message(Command("ringkasan"))
async def cmd_ringkasan(message: Message, session, user: User):
    await _render(message.bot, message.chat.id, None, session, user, "day")


@router.callback_query(F.data.startswith("sum:"))
async def sum_nav(cb: CallbackQuery, session, user: User):
    period_type = PERIODS.get(cb.data)
    if not period_type:
        return await cb.answer()
    await _render(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                  session, user, period_type)
    await cb.answer()


# ============================== 📊 Laporan (level 2-3) ==========================

@router.callback_query(F.data.startswith("rep:"))
async def rep_nav(cb: CallbackQuery, session, user: User):
    from app.keyboards.inline import back_kb, ikb

    data = cb.data
    bot, chat_id, message_id = cb.message.bot, cb.message.chat.id, cb.message.message_id

    if data == "rep:menu":
        kb = ikb([
            [("📆 Rentang Waktu", "rep:range")],
            [("🗓️ Pilih Bulan Spesifik", "rep:spec")],
            [("⬅️ Kembali", "rep:back")],
        ])
        await cb.message.edit_text(
            "📊 <b>Laporan</b>\n\nPilih jenis laporan:",
            reply_markup=kb,
        )

    elif data == "rep:back":
        await _render(bot, chat_id, message_id, session, user, "day")

    elif data == "rep:range":
        kb = ikb([
            [("1 Bulan Terakhir", "rep:r:1"), ("3 Bulan Terakhir", "rep:r:3")],
            [("6 Bulan Terakhir", "rep:r:6"), ("12 Bulan Terakhir", "rep:r:12")],
            [("⬅️ Kembali", "rep:menu")],
        ])
        await cb.message.edit_text(
            "📆 <b>Laporan Rentang</b>\n\nPilih rentang waktu:",
            reply_markup=kb,
        )

    elif data.startswith("rep:r:"):
        n = int(data.split(":")[2])
        today = today_local()
        start = shift_date("month", today, -(n - 1))
        end = month_window(today)[1]
        report = await SummaryService(session).build_range_summary(user.id, start, end)
        await _render_report(bot, chat_id, message_id, report,
                             f"Rentang {n} Bulan Terakhir", back_kb("rep:range"))

    elif data == "rep:spec":
        months = await TransactionRepo(session).available_months(user.id)
        if not months:
            await cb.message.edit_text(
                "🗓️ <b>Pilih Bulan Spesifik</b>\n\n"
                "Belum ada data transaksi untuk dipilih.\n"
                "Mulai catat: /catat atau ketik bebas seperti <i>beli kopi 25rb</i>",
                reply_markup=back_kb("rep:menu"),
            )
        else:
            years = sorted({y for y, _ in months}, reverse=True)
            rows = [[(f"📅 {y}", f"rep:y:{y}")] for y in years]
            rows.append([("⬅️ Kembali", "rep:menu")])
            await cb.message.edit_text(
                "🗓️ <b>Pilih Bulan Spesifik</b>\n\nPilih tahun (sesuai data yang ada):",
                reply_markup=ikb(rows),
            )

    elif data.startswith("rep:y:"):
        year = int(data.split(":")[2])
        months = await TransactionRepo(session).available_months(user.id)
        ms = sorted({m for y, m in months if y == year}, reverse=True)
        if not ms:
            return await cb.answer("Tidak ada data di tahun ini.", show_alert=True)
        rows = [[(f"{MONTHS_FULL[m - 1]} {year}", f"rep:m:{year:04d}-{m:02d}")] for m in ms]
        rows.append([("⬅️ Kembali", "rep:spec")])
        await cb.message.edit_text(
            f"🗓️ <b>Pilih Bulan — {year}</b>\n\nBulan yang punya data transaksi:",
            reply_markup=ikb(rows),
        )

    elif data.startswith("rep:m:"):
        year, month = map(int, data.split(":")[2].split("-"))
        report = await SummaryService(session).build_summary(
            user.id, "month", date(year, month, 1)
        )
        await _render_report(bot, chat_id, message_id, report,
                             f"{MONTHS_FULL[month - 1]} {year}", back_kb(f"rep:y:{year}"))

    await cb.answer()
