"""Transfer antar wallet (PRD §4 — tabel terpisah, tidak masuk laporan)."""

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.domain.enums import WALLET_TYPE_ICONS
from app.domain.money import format_rupiah, parse_amount
from app.handlers.states import TransferStates
from app.keyboards.inline import ikb, wallet_list_kb
from app.services.errors import ValidationError
from app.services.transfers import TransferService
from app.services.wallets import WalletService
from app.utils.format import today_local
from app.utils.messages import render_step

router = Router()


def _wallet_icon(w) -> str:
    return WALLET_TYPE_ICONS.get(w.type, "💼")


@router.message(Command("transfer"))
async def cmd_transfer(message: Message, state, session, user: User):
    wallets = await WalletService(session).list_with_balances(user.id)
    active = [(w, b) for w, b in wallets if w.is_active]
    if len(active) < 2:
        await message.answer("Transfer butuh minimal 2 wallet aktif. Buat wallet: /wallet")
        return
    await state.clear()
    await state.set_state(TransferStates.choosing_from_wallet)
    await state.update_data(msg_id=None)
    kb = wallet_list_kb([w for w, _ in active], "tf:from:", show_balance=True,
                        balance_lines={w.id: b for w, b in active})
    kb.inline_keyboard.append([_cancel_row()])
    await render_step(message.bot, message.chat.id, state, "📤 Dari wallet mana?", kb)


def _cancel_row():
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text="❌ Batal", callback_data="tf:cancel")


@router.callback_query(F.data == "tf:cancel")
async def tf_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.callback_query(F.data.startswith("tf:from:"), TransferStates.choosing_from_wallet)
async def tf_choose_from(cb: CallbackQuery, state, session, user: User):
    from_id = int(cb.data.split(":")[2])
    wallets = [w for w, _ in await WalletService(session).list_with_balances(user.id)
               if w.is_active and w.id != from_id]
    if not wallets:
        return await cb.answer("Tidak ada wallet tujuan lain.", show_alert=True)
    await state.update_data(from_wallet_id=from_id)
    await state.set_state(TransferStates.choosing_to_wallet)
    kb = wallet_list_kb(wallets, "tf:to:")
    kb.inline_keyboard.append([_cancel_row()])
    await render_step(cb.message.bot, cb.message.chat.id, state, "📥 Ke wallet mana?", kb)
    await cb.answer()


@router.callback_query(F.data.startswith("tf:to:"), TransferStates.choosing_to_wallet)
async def tf_choose_to(cb: CallbackQuery, state, session, user: User):
    to_id = int(cb.data.split(":")[2])
    from app.repositories.wallets import WalletRepo
    if not await WalletRepo(session).get_for_user(to_id, user.id):
        return await cb.answer("Wallet tidak valid.", show_alert=True)
    await state.update_data(to_wallet_id=to_id)
    await state.set_state(TransferStates.entering_amount)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "💰 Jumlah transfer (contoh: 100000, 250rb):",
        ikb([[("❌ Batal", "tf:cancel")]]),
    )
    await cb.answer()


@router.message(TransferStates.entering_amount)
async def tf_enter_amount(message: Message, state):
    value = parse_amount(message.text)
    if value is None:
        await message.answer("⚠️ Format jumlah tidak dikenali. Contoh: 100000, 250rb")
        return
    await state.update_data(amount=str(value))
    await state.set_state(TransferStates.entering_note)
    await render_step(
        message.bot, message.chat.id, state,
        "🗒️ Catatan (opsional) — kirim teks atau tekan Lewati:",
        ikb([[("⏭️ Lewati", "tf:skipnote")], [("❌ Batal", "tf:cancel")]]),
    )


@router.callback_query(F.data == "tf:skipnote", TransferStates.entering_note)
async def tf_skip_note(cb: CallbackQuery, state, session):
    await state.update_data(note=None)
    await state.set_state(TransferStates.confirming)
    await _render_confirm(cb.message, state, session)


async def _render_confirm(message, state, session):
    data = await state.get_data()
    from app.repositories.wallets import WalletRepo
    fw = await WalletRepo(session).get(data["from_wallet_id"])
    tw = await WalletRepo(session).get(data["to_wallet_id"])
    lines = [
        "🔄 <b>Konfirmasi Transfer</b>",
        f"Dari: {_wallet_icon(fw)} {fw.name}" if fw else "Dari: ?",
        f"Ke: {_wallet_icon(tw)} {tw.name}" if tw else "Ke: ?",
        f"Jumlah: <b>{format_rupiah(Decimal(data['amount']))}</b>",
    ]
    if data.get("note"):
        lines.append(f"Catatan: {data['note']}")
    await render_step(
        message.bot, message.chat.id, state, "\n".join(lines),
        ikb([[("✅ Simpan", "tf:save"), ("❌ Batal", "tf:cancel")]]),
    )


@router.message(TransferStates.entering_note)
async def tf_enter_note(message: Message, state, session):
    await state.update_data(note=message.text.strip()[:500])
    await state.set_state(TransferStates.confirming)
    await _render_confirm(message, state, session)


@router.callback_query(F.data == "tf:save", TransferStates.confirming)
async def tf_save(cb: CallbackQuery, state, session, user: User):
    data = await state.get_data()
    try:
        tf = await TransferService(session).create(
            user,
            from_wallet_id=data["from_wallet_id"],
            to_wallet_id=data["to_wallet_id"],
            amount=Decimal(data["amount"]),
            note=data.get("note"),
            occurred_at=today_local(),
        )
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await state.clear()
    from app.repositories.wallets import WalletRepo
    fw_row = await WalletRepo(session).get(data["from_wallet_id"])
    tw_row = await WalletRepo(session).get(data["to_wallet_id"])
    await cb.message.edit_text(
        f"✅ Transfer tersimpan!\n{_wallet_icon(fw_row)} {fw_row.name} → "
        f"{_wallet_icon(tw_row)} {tw_row.name}: <b>{format_rupiah(tf.amount)}</b>"
    )
    await cb.answer()
