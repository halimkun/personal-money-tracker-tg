"""Transaksi manual: /catat (FSM), /riwayat (list+pagination+filter), edit/hapus.

Pola UX (PRD §7): pilihan dari daftar & navigasi → edit message;
input free-text (jumlah/catatan) → FSM multi-step dengan tombol Batal.
Edit transaksi memakai callback token (PRD §7c).
"""

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from app.db.models import User
from app.domain.enums import WALLET_TYPE_ICONS
from app.domain.logic import can_add_transaction
from app.domain.money import format_rupiah, parse_amount
from app.handlers.states import AddTransactionStates, EditTransactionStates
from app.keyboards.inline import category_list_kb, ikb
from app.repositories.categories import CategoryRepo
from app.repositories.transactions import TransactionRepo
from app.repositories.wallets import WalletRepo
from app.services.callback_refs import CallbackRefService
from app.services.errors import FreemiumBlockedError, ValidationError
from app.services.settings import SettingsService
from app.services.transactions import TransactionService
from app.texts.id import MSG_FREEMIUM_BLOCKED
from app.utils.format import fmt_date_short, today_local
from app.utils.messages import edit_or_send, render_step

router = Router()

PER_PAGE = 5
CAT_PER_PAGE = 10
TYPE_LABELS = {"income": ("Pemasukan", "💰"), "expense": ("Pengeluaran", "💸")}
TYPE_REV = {"Semua": "all", "Pengeluaran": "expense", "Pemasukan": "income"}
TYPE_NAMES = {"all": "Semua", "expense": "Pengeluaran", "income": "Pemasukan"}


def _cancel_btn(cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="❌ Batal", callback_data=cb)


# ============================== /catat (FSM) =================================

@router.message(Command("catat"))
async def cmd_catat(message: Message, state, session, user: User):
    await state.clear()
    if not await WalletRepo(session).list_by_user(user.id, active_only=True):
        await message.answer("Buat wallet dulu ya: /wallet")
        return
    settings_svc = SettingsService(session)
    allowed, _ = can_add_transaction(
        user, await settings_svc.payment_required(), await settings_svc.free_limit()
    )
    if not allowed:
        await message.answer(MSG_FREEMIUM_BLOCKED)
        return

    await state.set_state(AddTransactionStates.choosing_type)
    await state.update_data(msg_id=None)
    await render_step(
        message.bot, message.chat.id, state, "📝 Mau catat apa?",
        ikb([[("💸 Pengeluaran", "tx:t:expense"), ("💰 Pemasukan", "tx:t:income")],
             [("❌ Batal", "tx:cancel")]]),
    )


async def _tx_summary(data: dict) -> str:
    label, icon = TYPE_LABELS[data["type"]]
    d = data.get("occurred_at_date")
    lines = [
        "📝 <b>Konfirmasi Transaksi</b>",
        f"Tipe: {icon} {label}",
        f"Jumlah: <b>{format_rupiah(Decimal(data['amount']))}</b>",
        f"Kategori: {data.get('category_name', '?')}",
        f"Wallet: {data.get('wallet_name', '?')}",
        f"Tanggal: {fmt_date_short(d) if d else 'Hari ini'}",
    ]
    if data.get("note"):
        lines.append(f"Catatan: {data['note']}")
    return "\n".join(lines)


@router.callback_query(F.data == "tx:cancel")
async def tx_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.callback_query(F.data.startswith("tx:t:"), AddTransactionStates.choosing_type)
async def tx_choose_type(cb: CallbackQuery, state):
    type_ = cb.data.split(":")[2]
    if type_ not in ("income", "expense"):
        return await cb.answer("Pilihan tidak valid.", show_alert=True)
    await state.update_data(type=type_)
    await state.set_state(AddTransactionStates.entering_amount)
    label, icon = TYPE_LABELS[type_]
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        f"{icon} Masukkan jumlah {label.lower()} (contoh: 25000, 25.000, 25rb, 2jt):",
        ikb([[("❌ Batal", "tx:cancel")]]),
    )
    await cb.answer()


@router.message(AddTransactionStates.entering_amount)
async def tx_enter_amount(message: Message, state, session, user: User):
    value = parse_amount(message.text)
    if value is None:
        await message.answer("⚠️ Format jumlah tidak dikenali. Contoh: 25000, 25.000, 25rb, 2jt")
        return
    await state.update_data(amount=str(value))
    await state.set_state(AddTransactionStates.choosing_wallet)
    wallets = await WalletRepo(session).list_by_user(user.id, active_only=True)
    kb = ikb(
        [[(f"{WALLET_TYPE_ICONS.get(w.type, '💼')} {w.name}", f"tx:w:{w.id}")] for w in wallets]
        + [[("❌ Batal", "tx:cancel")]]
    )
    await render_step(message.bot, message.chat.id, state, "👛 Pilih wallet:", kb)


@router.callback_query(F.data.startswith("tx:w:"), AddTransactionStates.choosing_wallet)
async def tx_choose_wallet(cb: CallbackQuery, state, session, user: User):
    wallet_id = int(cb.data.split(":")[2])
    wallet = await WalletRepo(session).get_for_user(wallet_id, user.id)
    if not wallet or not wallet.is_active:
        return await cb.answer("Wallet tidak ditemukan.", show_alert=True)
    await state.update_data(wallet_id=wallet.id, wallet_name=wallet.name)
    await state.set_state(AddTransactionStates.choosing_category)
    await _render_category_list(cb.message, state, session, user, "tx:", 0)
    await cb.answer()


async def _render_category_list(message, state, session, user: User, prefix: str, page: int):
    data = await state.get_data()
    categories = [c for c in await CategoryRepo(session).list_for_user(user.id) if c.type == data["type"]]
    total_pages = max(1, (len(categories) + CAT_PER_PAGE - 1) // CAT_PER_PAGE)
    page = min(max(page, 0), total_pages - 1)
    items = categories[page * CAT_PER_PAGE : (page + 1) * CAT_PER_PAGE]
    kb = category_list_kb(
        items, page, CAT_PER_PAGE, total_pages, page < total_pages - 1,
        select_prefix=f"{prefix}c:", page_prefix=f"{prefix}cpg:",
    )
    kb.inline_keyboard.append([_cancel_btn(f"{prefix}cancel")])
    await render_step(message.bot, message.chat.id, state, "🏷️ Pilih kategori:", kb)


@router.callback_query(F.data.startswith("tx:cpg:"), AddTransactionStates.choosing_category)
async def tx_category_page(cb: CallbackQuery, state, session, user: User):
    await _render_category_list(cb.message, state, session, user, "tx:", int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("tx:c:"), AddTransactionStates.choosing_category)
async def tx_choose_category(cb: CallbackQuery, state, session, user: User):
    category_id = int(cb.data.split(":")[2])
    data = await state.get_data()
    category = await CategoryRepo(session).get_usable(category_id, user.id)
    if not category or category.type != data["type"]:
        return await cb.answer("Kategori tidak valid.", show_alert=True)
    await state.update_data(
        category_id=category.id, category_name=f"{category.icon or ''} {category.name}".strip()
    )
    await state.set_state(AddTransactionStates.entering_note)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "🗒️ Catatan (opsional) — kirim teks atau tekan Lewati:",
        ikb([[("⏭️ Lewati", "tx:skipnote")], [("❌ Batal", "tx:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data == "tx:skipnote", AddTransactionStates.entering_note)
async def tx_skip_note(cb: CallbackQuery, state):
    await state.update_data(note=None)
    await state.set_state(AddTransactionStates.confirming)
    data = await state.get_data()
    await render_step(
        cb.message.bot, cb.message.chat.id, state, await _tx_summary(data),
        ikb([[("✅ Simpan", "tx:save"), ("❌ Batal", "tx:cancel")]]),
    )
    await cb.answer()


@router.message(AddTransactionStates.entering_note)
async def tx_enter_note(message: Message, state):
    await state.update_data(note=message.text.strip()[:500])
    await state.set_state(AddTransactionStates.confirming)
    data = await state.get_data()
    await render_step(
        message.bot, message.chat.id, state, await _tx_summary(data),
        ikb([[("✅ Simpan", "tx:save"), ("❌ Batal", "tx:cancel")]]),
    )


@router.callback_query(F.data == "tx:save", AddTransactionStates.confirming)
async def tx_save(cb: CallbackQuery, state, session, user: User):
    data = await state.get_data()
    try:
        tx, alerts = await TransactionService(session).create(
            user,
            type_=data["type"],
            amount=Decimal(data["amount"]),
            category_id=data["category_id"],
            wallet_id=data["wallet_id"],
            note=data.get("note"),
            occurred_at=data.get("occurred_at_date") or today_local(),
        )
    except FreemiumBlockedError:
        await state.clear()
        await cb.message.edit_text(MSG_FREEMIUM_BLOCKED)
        return await cb.answer()
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)

    await state.clear()
    label, icon = TYPE_LABELS[data["type"]]
    await cb.message.edit_text(
        f"✅ Tersimpan!\n{icon} {label} <b>{format_rupiah(tx.amount)}</b> — "
        f"{data.get('category_name', '')} • {data.get('wallet_name', '')}"
    )
    for alert in alerts:
        await cb.message.answer(alert)
    await cb.answer()


# ============================== /riwayat =====================================

async def _show_riwayat(bot, chat_id: int, message_id: int | None, session, user: User,
                        page: int, type_: str, wallet_id: int, category_id: int):
    rows, total = await TransactionRepo(session).list_paginated(
        user.id, page, PER_PAGE,
        type_=None if type_ == "all" else type_,
        wallet_id=wallet_id or None,
        category_id=category_id or None,
    )
    if total == 0:
        await edit_or_send(
            bot, chat_id, message_id,
            "📋 Belum ada transaksi. Mulai catat: /catat atau ketik bebas "
            "seperti <i>beli kopi 25rb</i>",
        )
        return

    lines = [f"📋 <b>Riwayat Transaksi</b> ({total})"]
    token_svc = CallbackRefService(session)
    row_buttons: list[list[tuple[str, str]]] = []
    for tx, cat_name, cat_icon in rows:
        label, icon = TYPE_LABELS[tx.type]
        lines.append(
            f"\n{fmt_date_short(tx.occurred_at)} — {cat_icon or ''} {cat_name} • "
            f"{icon} <b>{format_rupiah(tx.amount)}</b>"
        )
        if tx.note:
            lines.append(f"    <i>{tx.note}</i>")
        token = await token_svc.create(user.id, "edit_tx", {"tx_id": tx.id})
        row_buttons.append([("✏️", f"cb:{token}"), ("🗑", f"hist:del:{tx.id}")])

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    lines.append(f"\nHal. {page + 1}/{total_pages}")

    nav = []
    if page > 0:
        nav.append(("◀️", f"hist:{page - 1}:{type_}:{wallet_id}:{category_id}"))
    nav.append(("📋 Filter", f"hist:flt:{page}:{type_}:{wallet_id}:{category_id}"))
    if page < total_pages - 1:
        nav.append(("▶️", f"hist:{page + 1}:{type_}:{wallet_id}:{category_id}"))
    kb = ikb(row_buttons + [nav])
    await edit_or_send(bot, chat_id, message_id, "\n".join(lines), kb)


@router.message(Command("riwayat"))
async def cmd_riwayat(message: Message, session, user: User):
    await _show_riwayat(message.bot, message.chat.id, None, session, user, 0, "all", 0, 0)


@router.callback_query(F.data.startswith("hist:"))
async def hist_nav(cb: CallbackQuery, session, user: User):
    parts = cb.data.split(":")
    kind = parts[1]

    if kind.isdigit():  # hist:{page}:{type}:{wallet}:{cat}
        page, type_, wallet_id, category_id = int(parts[1]), parts[2], int(parts[3]), int(parts[4])
        await _show_riwayat(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                            session, user, page, type_, wallet_id, category_id)
    elif kind == "flt":  # hist:flt:{page}:{type}:{wallet}:{cat}
        page, type_, wallet_id, category_id = int(parts[2]), parts[3], int(parts[4]), int(parts[5])
        kb = ikb([
            [("👛 Wallet", f"hist:fw:{page}:{type_}:{category_id}")],
            [("🏷️ Kategori", f"hist:fc:{page}:{type_}:{wallet_id}")],
            [(f"💱 Tipe: {TYPE_NAMES[type_]}", f"hist:ft:{page}:{wallet_id}:{category_id}")],
            [("⬅️ Kembali", f"hist:{page}:{type_}:{wallet_id}:{category_id}")],
        ])
        await cb.message.edit_text("📋 <b>Filter Riwayat</b>", reply_markup=kb)
    elif kind == "fw":  # hist:fw:{page}:{type}:{cat}
        page, type_, cat = int(parts[2]), parts[3], int(parts[4])
        wallets = await WalletRepo(session).list_by_user(user.id, active_only=False)
        rows = [[("📁 Semua", f"hist:setw:0:{type_}:{cat}")]]
        rows += [[(f"{WALLET_TYPE_ICONS.get(w.type, '💼')} {w.name}", f"hist:setw:{w.id}:{type_}:{cat}")]
                 for w in wallets]
        rows.append([("⬅️ Kembali", f"hist:{page}:{type_}:0:{cat}")])
        await cb.message.edit_text("👛 <b>Filter Wallet</b>", reply_markup=ikb(rows))
    elif kind == "fc":  # hist:fc:{page}:{type}:{wallet}
        page, type_, wallet = int(parts[2]), parts[3], int(parts[4])
        categories = await CategoryRepo(session).list_for_user(user.id)
        rows = [[("📁 Semua", f"hist:setc:0:{type_}:{wallet}")]]
        rows += [[(f"{c.icon or '•'} {c.name} ({TYPE_NAMES.get(c.type, c.type)})",
                   f"hist:setc:{c.id}:{type_}:{wallet}")] for c in categories]
        rows.append([("⬅️ Kembali", f"hist:{page}:{type_}:{wallet}:0")])
        await cb.message.edit_text("🏷️ <b>Filter Kategori</b>", reply_markup=ikb(rows))
    elif kind == "ft":  # hist:ft:{page}:{wallet}:{cat}
        page, wallet, cat = int(parts[2]), int(parts[3]), int(parts[4])
        rows = [[(f"💱 {name}", f"hist:sett:{code}:{wallet}:{cat}")] for name, code in TYPE_REV.items()]
        rows.append([("⬅️ Kembali", f"hist:flt:{page}:all:{wallet}:{cat}")])
        await cb.message.edit_text("💱 <b>Filter Tipe</b>", reply_markup=ikb(rows))
    elif kind == "sett":  # hist:sett:{type}:{wallet}:{cat}
        type_, wallet, cat = parts[2], int(parts[3]), int(parts[4])
        await _show_riwayat(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                            session, user, 0, type_, wallet, cat)
    elif kind == "setw":  # hist:setw:{wallet}:{type}:{cat}
        wallet, type_, cat = int(parts[2]), parts[3], int(parts[4])
        await _show_riwayat(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                            session, user, 0, type_, wallet, cat)
    elif kind == "setc":  # hist:setc:{cat}:{type}:{wallet}
        cat, type_, wallet = int(parts[2]), parts[3], int(parts[4])
        await _show_riwayat(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                            session, user, 0, type_, wallet, cat)
    elif kind == "del":  # hist:del:{tx_id} — konfirmasi
        tx_id = int(parts[2])
        tx = await TransactionRepo(session).get_for_user(tx_id, user.id)
        if not tx:
            return await cb.answer("Transaksi tidak ditemukan.", show_alert=True)
        kb = ikb([
            [("🗑 Hapus", f"hist:dely:{tx_id}"), ("❌ Batal", "hist:delno")],
        ])
        await cb.message.edit_text(
            f"🗑 Yakin hapus transaksi ini?\n\n"
            f"{fmt_date_short(tx.occurred_at)} — <b>{format_rupiah(tx.amount)}</b>",
            reply_markup=kb,
        )
    elif kind == "dely":  # hist:dely:{tx_id} — eksekusi
        tx_id = int(parts[2])
        try:
            await TransactionService(session).delete(user, tx_id)
        except ValidationError as e:
            return await cb.answer(f"⚠️ {e}", show_alert=True)
        await cb.message.edit_text("🗑 Terhapus.")
    elif kind == "delno":
        await _show_riwayat(cb.message.bot, cb.message.chat.id, cb.message.message_id,
                            session, user, 0, "all", 0, 0)
    await cb.answer()


# ===================== Edit transaksi (via callback token) ===================

@router.callback_query(F.data.startswith("cb:"))
async def edit_tx_from_token(cb: CallbackQuery, state, session, user: User):
    payload = await CallbackRefService(session).resolve(cb.data[3:], user.id)
    if payload is None:
        return await cb.answer("Tombol ini sudah kedaluwarsa/tidak valid.", show_alert=True)
    if payload["purpose"] != "edit_tx":
        return await cb.answer("Aksi tidak dikenal.", show_alert=True)
    tx = await TransactionRepo(session).get_for_user(payload["tx_id"], user.id)
    if not tx:
        return await cb.answer("Transaksi tidak ditemukan.", show_alert=True)
    if await state.get_state():
        return await cb.answer("Selesaikan proses aktif dulu (/cancel).", show_alert=True)

    category = await CategoryRepo(session).get(tx.category_id)
    wallet = await WalletRepo(session).get(tx.wallet_id)
    await state.set_state(EditTransactionStates.choosing_amount)
    await state.update_data(
        edit_tx_id=tx.id, type=tx.type,
        wallet_id=tx.wallet_id, wallet_name=wallet.name if wallet else "?",
        amount=str(tx.amount),
        category_id=tx.category_id,
        category_name=f"{category.icon or ''} {category.name}".strip() if category else "?",
        note=tx.note, msg_id=None,
    )
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        f"✏️ Edit transaksi — jumlah baru? (sekarang <b>{format_rupiah(tx.amount)}</b>):",
        ikb([[("❌ Batal", "edit:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data == "edit:cancel")
async def edit_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Edit dibatalkan.")
    await cb.answer()


@router.message(EditTransactionStates.choosing_amount)
async def edit_enter_amount(message: Message, state):
    value = parse_amount(message.text)
    if value is None:
        await message.answer("⚠️ Format jumlah tidak dikenali. Contoh: 25000, 25.000, 25rb, 2jt")
        return
    await state.update_data(amount=str(value))
    await state.set_state(EditTransactionStates.choosing_category)
    await _render_edit_category(message, state, 0)


async def _render_edit_category(message, state, session, user: User, page: int):
    data = await state.get_data()
    categories = [c for c in await CategoryRepo(session).list_for_user(user.id)
                  if c.type == data["type"]]
    total_pages = max(1, (len(categories) + CAT_PER_PAGE - 1) // CAT_PER_PAGE)
    page = min(max(page, 0), total_pages - 1)
    items = categories[page * CAT_PER_PAGE : (page + 1) * CAT_PER_PAGE]
    kb = category_list_kb(
        items, page, CAT_PER_PAGE, total_pages, page < total_pages - 1,
        select_prefix="edit:c:", page_prefix="edit:cpg:",
    )
    kb.inline_keyboard.append([_cancel_btn("edit:cancel")])
    await render_step(
        message.bot, message.chat.id, state,
        f"🏷️ Kategori baru? (sekarang: <b>{data.get('category_name', '?')}</b>):", kb,
    )


@router.callback_query(F.data.startswith("edit:cpg:"), EditTransactionStates.choosing_category)
async def edit_category_page(cb: CallbackQuery, state, session, user: User):
    await _render_edit_category(cb.message, state, session, user, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("edit:c:"), EditTransactionStates.choosing_category)
async def edit_choose_category(cb: CallbackQuery, state, session, user: User):
    category_id = int(cb.data.split(":")[2])
    data = await state.get_data()
    category = await CategoryRepo(session).get_usable(category_id, user.id)
    if not category or category.type != data["type"]:
        return await cb.answer("Kategori tidak valid.", show_alert=True)
    await state.update_data(
        category_id=category.id, category_name=f"{category.icon or ''} {category.name}".strip()
    )
    await state.set_state(EditTransactionStates.entering_note)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        f"🗒️ Catatan baru? (sekarang: <i>{data.get('note') or '—'}</i>)",
        ikb([[("⏭️ Lewati", "edit:skipnote")], [("❌ Batal", "edit:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data == "edit:skipnote", EditTransactionStates.entering_note)
async def edit_skip_note(cb: CallbackQuery, state):
    await state.update_data(note=None)
    await state.set_state(EditTransactionStates.confirming)
    await render_step(
        cb.message.bot, cb.message.chat.id, state, await _edit_summary(state),
        ikb([[("✅ Simpan", "edit:save"), ("❌ Batal", "edit:cancel")]]),
    )
    await cb.answer()


@router.message(EditTransactionStates.entering_note)
async def edit_enter_note(message: Message, state):
    await state.update_data(note=message.text.strip()[:500])
    await state.set_state(EditTransactionStates.confirming)
    await render_step(
        message.bot, message.chat.id, state, await _edit_summary(state),
        ikb([[("✅ Simpan", "edit:save"), ("❌ Batal", "edit:cancel")]]),
    )


async def _edit_summary(state) -> str:
    data = await state.get_data()
    lines = ["✏️ <b>Konfirmasi Edit</b>"] + (await _tx_summary(data)).split("\n")[1:]
    return "\n".join(lines)


@router.callback_query(F.data == "edit:save", EditTransactionStates.confirming)
async def edit_save(cb: CallbackQuery, state, session, user: User):
    data = await state.get_data()
    try:
        await TransactionService(session).update(
            user,
            tx_id=data["edit_tx_id"],
            amount=Decimal(data["amount"]),
            category_id=data["category_id"],
            note=data.get("note"),
        )
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await state.clear()
    await cb.message.edit_text(
        f"✅ Transaksi diperbarui: <b>{format_rupiah(Decimal(data['amount']))}</b> — "
        f"{data.get('category_name', '')}"
    )
    await cb.answer()
