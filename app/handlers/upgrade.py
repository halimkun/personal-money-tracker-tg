"""Upgrade premium — Opsi A: transfer manual + approval admin (PRD §5.3).

Pola UX (PRD §7): prompt kirim bukti adalah pesan BARU; saat foto diterima,
prompt itu di-edit untuk konfirmasi via `confirm_step`.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db.models import User
from app.domain.money import format_rupiah
from app.handlers.states import UpgradeStates
from app.keyboards.inline import ikb
from app.services.callback_refs import CallbackRefService
from app.services.errors import ValidationError
from app.services.payments import PaymentService
from app.services.settings import SettingsService
from app.texts.id import UPGRADE_CANCEL_HELP
from app.utils.format import fmt_datetime
from app.utils.messages import confirm_step, render_step

router = Router()


def _premium_status(user: User) -> str:
    if not user.is_premium:
        return "Free"
    if user.premium_until is None:
        return "Premium seumur hidup ♾️"
    return f"Premium s.d. {fmt_datetime(user.premium_until)}"


async def _render(bot, chat_id: int, message_id: int | None, session, user: User):
    svc = SettingsService(session)
    price = await svc.premium_price()
    days = await svc.premium_duration_days()
    instructions = await svc.payment_instructions()
    lines = [
        "⭐ <b>Upgrade Premium</b>",
        "",
        f"Status kamu: <b>{_premium_status(user)}</b>",
        f"Harga: <b>{format_rupiah(price)}</b> / {days} hari",
        "",
        instructions,
    ]
    rows = []
    if not user.is_premium:
        rows.append([("📤 Kirim Bukti Transfer", "upg:pay")])
    kb = ikb(rows) if rows else None
    from app.utils.messages import edit_or_send
    await edit_or_send(bot, chat_id, message_id, "\n".join(lines), kb)


@router.message(Command("upgrade"))
async def cmd_upgrade(message: Message, session, user: User):
    await _render(message.bot, message.chat.id, None, session, user)


@router.callback_query(F.data == "upg:pay")
async def upg_start(cb: CallbackQuery, state, session, user: User):
    if await state.get_state():
        # user sedang di proses lain — jangan bajak state (mis. tombol panel lama)
        return await cb.answer("Selesaikan proses aktif dulu (/cancel).", show_alert=True)
    svc = SettingsService(session)
    price = await svc.premium_price()
    await state.set_state(UpgradeStates.waiting_proof_photo)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        f"📤 Transfer sebesar <b>{format_rupiah(price)}</b> sesuai instruksi, lalu "
        "kirim <b>foto/screenshot bukti transfer</b> ke sini.\n\n"
        f"{UPGRADE_CANCEL_HELP}",
        ikb([[("❌ Batal", "upg:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data == "upg:cancel")
async def upg_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.message(UpgradeStates.waiting_proof_photo, F.photo)
async def upg_receive_proof(message: Message, state, session, user: User):
    price = await SettingsService(session).premium_price()
    photo = message.photo[-1]
    try:
        payment = await PaymentService(session).create(user, price, photo.file_id)
    except ValidationError as e:
        await message.answer(f"⚠️ {e}")
        return
    await confirm_step(message.bot, message.chat.id, state, "📷 Foto bukti diterima")
    await state.clear()

    # Token dibuat PER-ADMIN karena resolve() memvalidasi kepemilikan user_id (PRD §7c)
    token_svc = CallbackRefService(session)
    admin_text = (
        f"💳 <b>Pembayaran Premium Baru</b>\n\n"
        f"User: {user.full_name or '—'} (@{user.username or '—'}) — id {user.telegram_id}\n"
        f"Jumlah: <b>{format_rupiah(payment.amount)}</b>\n"
        f"ID: {payment.id} · {fmt_datetime(payment.created_at)}\n\n"
        "Foto bukti dikirim sebagai pesan terpisah di bawah."
    )
    for admin_id in settings.admin_set:
        approve_token = await token_svc.create(admin_id, "payment_decision",
                                               {"payment_id": payment.id, "action": "approve"})
        reject_token = await token_svc.create(admin_id, "payment_decision",
                                              {"payment_id": payment.id, "action": "reject"})
        kb = ikb([[("✅ Approve", f"ap:{approve_token}"), ("❌ Tolak", f"ap:{reject_token}")]])
        try:
            await message.bot.send_message(admin_id, admin_text, reply_markup=kb)
            await message.bot.send_photo(admin_id, photo.file_id)
        except Exception:
            continue

    await message.answer(
        "✅ Bukti pembayaran diterima! Admin akan memverifikasi dalam 1×24 jam. "
        "Status bisa dicek dengan /status."
    )
