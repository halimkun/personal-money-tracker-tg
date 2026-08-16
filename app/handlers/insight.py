"""AI insight bulanan (PRD §5.4) — generate on-demand + lihat riwayat."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.ai.client import AIError
from app.db.models import User
from app.keyboards.inline import ikb
from app.services.errors import ValidationError
from app.services.insights import InsightsService
from app.texts.id import MSG_AI_FAIL
from app.utils.format import today_local
from app.utils.messages import edit_or_send

router = Router()


@router.message(Command("insight"))
async def cmd_insight(message: Message):
    await edit_or_send(
        message.bot, message.chat.id, None,
        "🧠 <b>Insight Keuangan AI</b>\n\n"
        "AI menganalisis pola pengeluaran bulan ini dari data agregat "
        "(tanpa membaca detail transaksi satu per satu) dan memberi saran.",
        ikb([[("✨ Buat Insight Bulan Ini", "ins:gen")],
             [("🗂️ Riwayat Insight", "ins:hist")]]),
    )


@router.callback_query(F.data == "ins:gen")
async def ins_generate(cb: CallbackQuery, session, user: User):
    await cb.answer("🧠 AI sedang menganalisis... mungkin butuh beberapa detik")
    try:
        content = await InsightsService(session).generate(user, today_local())
    except ValidationError as e:
        return await cb.message.edit_text(f"⚠️ {e}")
    except AIError:
        return await cb.message.edit_text(MSG_AI_FAIL)
    await cb.message.edit_text(content, reply_markup=ikb([[("🗂️ Riwayat", "ins:hist")]]))


@router.callback_query(F.data == "ins:hist")
async def ins_history(cb: CallbackQuery, session, user: User):
    items = await InsightsService(session).history(user.id)
    if not items:
        await cb.message.edit_text(
            "🗂️ Belum ada insight tersimpan. Tekan ✨ Buat untuk membuat yang pertama."
        )
        return await cb.answer()
    lines = ["🗂️ <b>Riwayat Insight</b>", ""]
    rows = []
    for it in items:
        period = f"{it.period[:4]}-{it.period[5:7]}"  # "2026-08"
        preview = " ".join(it.content.split())[:60]
        lines.append(f"📅 {period} — {preview}…")
        rows.append([(f"📅 {period}", f"ins:view:{it.id}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("ins:view:"))
async def ins_view(cb: CallbackQuery, session, user: User):
    insight = await InsightsService(session).get(user.id, int(cb.data.split(":")[2]))
    if not insight:
        return await cb.answer("Insight tidak ditemukan.", show_alert=True)
    await cb.message.edit_text(insight.content)
    await cb.answer()
