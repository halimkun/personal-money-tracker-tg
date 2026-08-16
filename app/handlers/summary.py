"""Laporan ringkasan harian/mingguan/bulanan (PRD §5.1)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.domain.money import format_rupiah
from app.services.summary import SummaryService
from app.utils.format import fmt_date_short, today_local
from app.utils.messages import edit_or_send

router = Router()

PERIODS = {"sum:d": "day", "sum:w": "week", "sum:m": "month"}
PERIOD_NAMES = {"day": "Hari Ini", "week": "Minggu Ini", "month": "Bulan Ini"}


async def _render(bot, chat_id: int, message_id: int | None, session, user: User,
                  period_type: str):
    data = await SummaryService(session).build_summary(user.id, period_type, today_local())
    if data["tx_count"] == 0:
        text = (
            f"📊 <b>{PERIOD_NAMES[period_type]}</b>\n\n"
            "Belum ada transaksi di periode ini.\n"
            "Mulai catat: /catat atau ketik bebas seperti <i>beli kopi 25rb</i>"
        )
    else:
        lines = [f"📊 <b>{PERIOD_NAMES[period_type]}</b>"]
        if period_type != "day":
            lines.append(f"{fmt_date_short(data['start'])} – {fmt_date_short(data['end'])}")
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
            from app.services.summary import pct_delta
            delta = pct_delta(data["expense"], data["prev_expense"])
            if delta:
                up = data["expense"] >= data["prev_expense"]
                arrow = "📈" if up else "📉"
                lines.append(f"\n{arrow} vs periode sebelumnya: {delta}")
        text = "\n".join(lines)

    from app.keyboards.inline import ikb
    marks = {ptype: ("✅ " if ptype == period_type else "") for ptype in PERIODS.values()}
    kb = ikb([[
        (f"{marks['day']}📅 Hari", "sum:d"),
        (f"{marks['week']}📆 Minggu", "sum:w"),
        (f"{marks['month']}🗓️ Bulan", "sum:m"),
    ]])
    await edit_or_send(bot, chat_id, message_id, text, kb)


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
