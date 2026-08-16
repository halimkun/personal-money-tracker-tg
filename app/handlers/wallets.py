"""Kelola wallet: daftar+saldo, tambah, rename, default, nonaktifkan (PRD §4, §5.1).

Pola UX FSM (PRD §7): tiap prompt langkah pesan BARU; jawaban user ditempel
di prompt sebelumnya via `confirm_step`. Menu daftar wallet tetap di-update
di tempat.
"""

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.domain.enums import WALLET_TYPE_ICONS, WALLET_TYPE_LABELS
from app.domain.money import format_rupiah, parse_amount
from app.handlers.states import WalletStates
from app.keyboards.inline import ikb
from app.services.errors import ValidationError
from app.services.wallets import WalletService
from app.texts.id import WELCOME_WALLET_DONE
from app.utils.messages import confirm_step, edit_or_send, render_step

router = Router()

TYPE_CHOICES = [("cash", "💵 Tunai"), ("bank", "🏦 Bank"),
                ("ewallet", "📱 E-Wallet"), ("other", "💼 Lainnya")]
TYPE_LABELS_MAP = dict(TYPE_CHOICES)


async def _render_menu(bot, chat_id: int, message_id: int | None, session, user: User):
    items = await WalletService(session).list_with_balances(user.id)
    lines = ["👛 <b>Wallet Saya</b>", ""]
    rows = []
    for w, balance in items:
        icon = WALLET_TYPE_ICONS.get(w.type, "💼")
        badges = []
        if w.is_default:
            badges.append("⭐")
        if not w.is_active:
            badges.append("nonaktif")
        suffix = f" {' '.join(badges)}" if badges else ""
        lines.append(f"{icon} <b>{w.name}</b>{suffix} — {format_rupiah(balance)}")
        rows.append([(f"{icon} {w.name}", f"wl:sel:{w.id}")])
    rows.append([("➕ Tambah Wallet", "wl:add")])
    await edit_or_send(bot, chat_id, message_id, "\n".join(lines), ikb(rows))


@router.message(Command("wallet"))
async def cmd_wallet(message: Message, session, user: User):
    await _render_menu(message.bot, message.chat.id, None, session, user)


@router.callback_query(F.data == "wl:back")
async def wl_back(cb: CallbackQuery, session, user: User):
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer()


async def _render_detail(bot, chat_id: int, message_id: int | None, session, user: User,
                         wallet_id: int) -> bool:
    """Detail wallet (info) — update pesan di tempat. False kalau tidak ditemukan."""
    items = await WalletService(session).list_with_balances(user.id)
    wallet, balance = next(((w, b) for w, b in items if w.id == wallet_id), (None, None))
    if not wallet:
        return False
    icon = WALLET_TYPE_ICONS.get(wallet.type, "💼")
    lines = [
        f"{icon} <b>{wallet.name}</b>",
        f"Tipe: {WALLET_TYPE_LABELS.get(wallet.type, wallet.type)}",
        f"Saldo: <b>{format_rupiah(balance)}</b>",
        f"Status: {'🟢 aktif' if wallet.is_active else '🔴 nonaktif'}",
    ]
    if wallet.is_default:
        lines.append("⭐ Wallet default (dipakai AI saat tidak menyebut wallet)")
    kb_rows = []
    if wallet.is_active:
        if not wallet.is_default:
            kb_rows.append([(f"⭐ Jadikan Default", f"wl:def:{wallet.id}")])
        kb_rows.append([(f"✏️ Ganti Nama", f"wl:ren:{wallet.id}")])
        kb_rows.append([(f"🚫 Nonaktifkan", f"wl:off:{wallet.id}")])
    kb_rows.append([("⬅️ Kembali", "wl:back")])
    await edit_or_send(bot, chat_id, message_id, "\n".join(lines), ikb(kb_rows))
    return True


@router.callback_query(F.data.startswith("wl:sel:"))
async def wl_detail(cb: CallbackQuery, session, user: User):
    if not await _render_detail(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                                session, user, int(cb.data.split(":")[2])):
        return await cb.answer("Wallet tidak ditemukan.", show_alert=True)
    await cb.answer()


@router.callback_query(F.data.startswith("wl:def:"))
async def wl_set_default(cb: CallbackQuery, session, user: User):
    wallet_id = int(cb.data.split(":")[2])
    try:
        await WalletService(session).set_default(user.id, wallet_id)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer("⭐ Wallet default diubah")


@router.callback_query(F.data.startswith("wl:off:"))
async def wl_deactivate(cb: CallbackQuery, session, user: User):
    wallet_id = int(cb.data.split(":")[2])
    try:
        await WalletService(session).deactivate(user.id, wallet_id)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer("Wallet dinonaktifkan")


# ============================== FSM tambah/rename =============================

@router.callback_query(F.data == "wl:cancel")
async def wl_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.callback_query(F.data == "wl:add")
async def wl_add(cb: CallbackQuery, state, session, user: User):
    await state.set_state(WalletStates.entering_name)
    # ingat pesan menu asal — di-refresh di tempat saat wallet selesai dibuat
    await state.update_data(wallet_task="add", menu_msg_id=cb.message.message_id)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "💼 Nama wallet baru (mis. <b>OVO</b>, <b>Mandiri</b>):",
        ikb([[("❌ Batal", "wl:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("wl:ren:"))
async def wl_rename_start(cb: CallbackQuery, state):
    wallet_id = int(cb.data.split(":")[2])
    await state.set_state(WalletStates.entering_name)
    # ingat pesan detail asal — di-refresh di tempat saat rename selesai
    await state.update_data(wallet_task="rename", wallet_id=wallet_id,
                            detail_msg_id=cb.message.message_id)
    await render_step(
        cb.message.bot, cb.message.chat.id, state, "✏️ Nama baru wallet:",
        ikb([[("❌ Batal", "wl:cancel")]]),
    )
    await cb.answer()


@router.message(WalletStates.entering_name)
async def wl_enter_name(message: Message, state, session, user: User):
    data = await state.get_data()
    task = data.get("wallet_task", "add")
    name = message.text.strip()[:100]
    if task == "rename":
        try:
            await WalletService(session).rename(user.id, data["wallet_id"], name)
        except ValidationError as e:
            await message.answer(f"⚠️ {e}")
            return
        await confirm_step(message.bot, message.chat.id, state, f"✏️ {name}")
        await state.clear()
        await message.answer("✅ Nama wallet diubah.")
        await _render_detail(message.bot, message.chat.id, data.get("detail_msg_id"),
                             session, user, data["wallet_id"])
        return

    await state.update_data(wallet_name=name)
    await state.set_state(WalletStates.choosing_type)
    await confirm_step(message.bot, message.chat.id, state, f"💼 {name}")
    rows = [[(label, f"wl:type:{code}") for code, label in TYPE_CHOICES[i : i + 2]]
            for i in range(0, len(TYPE_CHOICES), 2)]
    rows.append([("❌ Batal", "wl:cancel")])
    await render_step(message.bot, message.chat.id, state, "🏦 Tipe wallet?", ikb(rows))


@router.callback_query(F.data.startswith("wl:type:"), WalletStates.choosing_type)
async def wl_choose_type(cb: CallbackQuery, state):
    type_ = cb.data.split(":")[2]
    if type_ not in ("cash", "bank", "ewallet", "other"):
        return await cb.answer("Tipe tidak valid.", show_alert=True)
    await state.update_data(wallet_type=type_)
    await state.set_state(WalletStates.entering_initial_balance)
    await confirm_step(cb.message.bot, cb.message.chat.id, state,
                       f"Anda memilih: {TYPE_LABELS_MAP[type_]}")
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "💰 Saldo awal? (ketik <b>0</b> kalau kosong — contoh: 100000, 250rb):",
        ikb([[("❌ Batal", "wl:cancel")]]),
    )
    await cb.answer()


@router.message(WalletStates.entering_initial_balance)
async def wl_enter_balance(message: Message, state, session, user: User):
    value = parse_amount(message.text, allow_zero=True)
    if value is None:
        await message.answer("⚠️ Format jumlah tidak dikenali. Contoh: 100000, 250rb, 0")
        return
    data = await state.get_data()
    try:
        await WalletService(session).create(
            user.id, data["wallet_name"], data["wallet_type"], value
        )
    except ValidationError as e:
        await message.answer(f"⚠️ {e}")
        return
    task = data.get("wallet_task", "add")
    await confirm_step(message.bot, message.chat.id, state, f"💵 {format_rupiah(value)}")
    await state.clear()
    if task == "start":
        await message.answer(WELCOME_WALLET_DONE)
    else:
        await message.answer("✅ Wallet dibuat.")
        await _render_menu(message.bot, message.chat.id, data.get("menu_msg_id"), session, user)
