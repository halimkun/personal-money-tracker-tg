"""Quick-add via AI (PRD §5.1b): teks bebas / foto struk → kartu konfirmasi wajib.

Router ini DIDAFFTARKAN PALING AKHIR (lihat handlers/__init__.py) karena memuat
handler generik untuk SEMUA teks/foto — handler FSM di router lain harus menang
lebih dulu. LockingMiddleware juga menjamin pesan saat state aktif tidak sampai
ke AI (hemat biaya).

Pola UX: kartu konfirmasi adalah SATU pesan yang di-update di tempat (PRD §7
konfirmasi) — koreksi jumlah/catatan/kategori/wallet menimpa kartu itu sendiri
lewat render_step(edit=True), dan kartu selalu menampilkan nilai hasil koreksi.
"""

import base64
from datetime import date, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from app.ai import quick_add as qa_ai
from app.ai.client import AIError
from app.ai.tracker import rate_limiter
from app.config import settings
from app.db.models import User
from app.domain.enums import WALLET_TYPE_ICONS
from app.domain.logic import can_add_transaction
from app.domain.money import format_rupiah, parse_amount
from app.handlers.states import QuickAddCorrectionStates, QuickAddStates
from app.keyboards.inline import category_list_kb, ikb, quick_add_card_kb, wallet_list_kb
from app.repositories.categories import CategoryRepo
from app.repositories.wallets import WalletRepo
from app.scheduler.drafts import DraftEntry, draft_registry
from app.services.errors import FreemiumBlockedError, ValidationError
from app.services.settings import SettingsService
from app.services.transactions import TransactionService
from app.services.transfers import TransferService
from app.texts.id import MSG_AI_FAIL, MSG_AI_LIMIT, MSG_AI_UNCLEAR, MSG_FREEMIUM_BLOCKED
from app.utils.format import fmt_date_short, now_utc_naive, today_local
from app.utils.messages import edit_or_send, render_step

router = Router()

CAT_PER_PAGE = 10


# ============================== Kartu konfirmasi ==============================

def _card_date(data: dict) -> str:
    """Tanggal kartu: dari AI (qa_date) atau 'Hari ini'."""
    qa_date = data.get("qa_date")
    return fmt_date_short(date.fromisoformat(qa_date)) if qa_date else "Hari ini"


def _clamp_date(date_iso: str | None) -> str | None:
    """Validasi tanggal AI: ISO valid & maksimal ±365 hari dari hari ini."""
    if not date_iso:
        return None
    try:
        d = date.fromisoformat(date_iso)
    except ValueError:
        return None
    if abs((d - today_local()).days) > 365:
        return None
    return d.isoformat()


def _card_text(data: dict) -> str:
    progress = (f" ({data.get('qa_pos', 1)}/{data.get('qa_total', 1)})"
                if data.get("qa_total", 1) > 1 else "")
    if data["qa_action"] == "transaction":
        label, icon = ("Pemasukan", "💰") if data["qa_type"] == "income" else ("Pengeluaran", "💸")
        lines = [
            f"🤖 <b>Transaksi Terdeteksi</b>{progress}",
            f"{icon} {label}",
            f"Jumlah: <b>{format_rupiah(Decimal(data['qa_amount']))}</b>",
            f"Kategori: {data['qa_category_name']}",
            f"Wallet: {data['qa_wallet_name']}",
            f"Tanggal: {_card_date(data)}",
        ]
    else:
        lines = [
            "🤖 <b>Transfer Terdeteksi</b>",
            f"Dari: {data['qa_from_name']}",
            f"Ke: {data['qa_to_name']}",
            f"Jumlah: <b>{format_rupiah(Decimal(data['qa_amount']))}</b>",
            f"Tanggal: {_card_date(data)}",
        ]
    if data.get("qa_note"):
        lines.append(f"Catatan: {data['qa_note']}")
    lines += ["", "Periksa detailnya, lalu tekan <b>✅ Simpan</b> atau ubah dulu."]
    return "\n".join(lines)


def _card_kb(data: dict):
    kind = "transaction" if data["qa_action"] == "transaction" else "transfer"
    return quick_add_card_kb(kind, multi=data.get("qa_total", 1) > 1)


async def _render_card(bot, chat_id: int, state) -> None:
    data = await state.get_data()
    msg_id = await edit_or_send(bot, chat_id, data.get("msg_id"), _card_text(data), _card_kb(data))
    await state.update_data(msg_id=msg_id)


def _name_with_icon(w) -> str:
    return f"{WALLET_TYPE_ICONS.get(w.type, '💼')} {w.name}"


# ============================== Entri pesan ===================================

async def _has_wallets(session, user: User) -> bool:
    """Wallet aktif minimal 1 (cek sebelum memanggil AI — hemat biaya)."""
    return bool(await WalletRepo(session).list_by_user(user.id, active_only=True))


async def _resolve_item_data(session, user: User, item) -> dict | None:
    """Resolusi satu item multi → data kartu; None kalau tidak bisa disimpan."""
    category = await qa_ai.resolve_category(session, user.id, item.category_guess, item.type)
    wallet = await qa_ai.resolve_wallet(session, user.id, item.wallet_guess)
    if not wallet:
        return None
    return dict(
        qa_action="transaction",
        qa_type=item.type,
        qa_amount=str(item.amount),
        qa_category_id=category.id,
        qa_category_name=f"{category.icon or ''} {category.name}".strip(),
        qa_wallet_id=wallet.id,
        qa_wallet_name=_name_with_icon(wallet),
        qa_note=item.note,
        qa_date=_clamp_date(item.date_iso),
    )


async def _handle_result(bot, chat_id: int, state, session, user: User, result,
                         *, source: str, source_file_id: str | None = None) -> None:
    """PRD §5.1b poin 3-5: unclear → balas singkat; jelas → kartu konfirmasi.

    Multi-item: satu kartu per transaksi, dikonfirmasi berurutan (qa_queue).
    """
    if result.is_unclear:
        await bot.send_message(chat_id, MSG_AI_UNCLEAR)
        return

    entries: list[dict] = []
    if result.action == "multi":
        for item in result.items or []:
            item_data = await _resolve_item_data(session, user, item)
            if item_data:
                entries.append(item_data)
        if not entries:
            await bot.send_message(chat_id, MSG_AI_UNCLEAR)
            return
        settings_svc = SettingsService(session)
        allowed, _ = can_add_transaction(
            user, await settings_svc.payment_required(), await settings_svc.free_limit()
        )
        if not allowed:
            await bot.send_message(chat_id, MSG_FREEMIUM_BLOCKED)
            return
    elif result.action == "transaction":
        if result.type is None:
            await bot.send_message(chat_id, MSG_AI_UNCLEAR)
            return
        category = await qa_ai.resolve_category(session, user.id, result.category_guess, result.type)
        wallet = await qa_ai.resolve_wallet(session, user.id, result.wallet_guess)
        if not wallet:
            await bot.send_message(chat_id, "Buat wallet dulu ya: /wallet")
            return
        settings_svc = SettingsService(session)
        allowed, _ = can_add_transaction(
            user, await settings_svc.payment_required(), await settings_svc.free_limit()
        )
        if not allowed:
            await bot.send_message(chat_id, MSG_FREEMIUM_BLOCKED)
            return
        entries.append(dict(
            qa_action="transaction",
            qa_type=result.type,
            qa_amount=str(result.amount),
            qa_category_id=category.id,
            qa_category_name=f"{category.icon or ''} {category.name}".strip(),
            qa_wallet_id=wallet.id,
            qa_wallet_name=_name_with_icon(wallet),
            qa_note=result.note,
            qa_date=_clamp_date(result.date_iso),
        ))
    else:  # transfer
        fw = await qa_ai.resolve_wallet(session, user.id, result.from_wallet_guess)
        tw = await qa_ai.resolve_wallet(session, user.id, result.to_wallet_guess)
        if not fw:
            await bot.send_message(chat_id, "Buat wallet dulu ya: /wallet")
            return
        if not tw or tw.id == fw.id:
            others = [w for w in await WalletRepo(session).list_by_user(user.id, active_only=True)
                      if w.id != fw.id]
            if not others:
                await bot.send_message(
                    chat_id, "Transfer butuh minimal 2 wallet aktif. Buat lagi: /wallet"
                )
                return
            tw = others[0]
        entries.append(dict(
            qa_action="transfer",
            qa_amount=str(result.amount),
            qa_from_id=fw.id, qa_from_name=_name_with_icon(fw),
            qa_to_id=tw.id, qa_to_name=_name_with_icon(tw),
            qa_note=result.note,
            qa_date=_clamp_date(result.date_iso),
        ))

    total = len(entries)
    for i, item in enumerate(entries, start=1):
        item["qa_pos"], item["qa_total"] = i, total
    data = dict(entries[0])
    data.update(qa_queue=entries[1:], qa_source=source,
                qa_source_file_id=source_file_id, msg_id=None)
    await state.set_state(QuickAddStates.awaiting_confirmation)
    await state.set_data(data)
    card_id = await edit_or_send(bot, chat_id, None, _card_text(data), _card_kb(data))
    await state.update_data(msg_id=card_id)
    draft_registry.register(DraftEntry(
        user.id, chat_id, card_id,
        now_utc_naive() + timedelta(minutes=settings.quick_add_draft_ttl_minutes),
    ))


@router.message(F.text)
async def quick_add_text(message: Message, state, session, user: User):
    if await state.get_state():
        return  # jaga-jaga: FSM di router lain harusnya sudah menangkap
    if not await _has_wallets(session, user):
        await message.answer("Buat wallet dulu ya: /wallet")
        return
    if not await rate_limiter.allow(session, user.id):
        await message.answer(MSG_AI_LIMIT)
        return
    try:
        result = await qa_ai.parse_text(session, user.id, message.text)
    except AIError:
        await message.answer(MSG_AI_FAIL)
        return
    rate_limiter.record(user.id)
    await _handle_result(message.bot, message.chat.id, state, session, user,
                         result, source="ai_text")


@router.message(F.photo)
async def quick_add_photo(message: Message, state, session, user: User):
    if await state.get_state():
        return
    if not await WalletRepo(session).list_by_user(user.id, active_only=True):
        await message.answer("Buat wallet dulu ya: /wallet")
        return
    if not await rate_limiter.allow(session, user.id):
        await message.answer(MSG_AI_LIMIT)
        return
    photo = message.photo[-1]
    file = await message.bot.download(photo.file_id)
    image_b64 = base64.b64encode(file.read()).decode()
    try:
        result = await qa_ai.parse_image(session, user.id, image_b64)
    except AIError:
        await message.answer(MSG_AI_FAIL)
        return
    rate_limiter.record(user.id)
    if message.caption and not result.note:
        result.note = message.caption.strip()[:200]
    await _handle_result(message.bot, message.chat.id, state, session, user,
                         result, source="ai_image", source_file_id=photo.file_id)


# ============================== Simpan / Batal ================================

@router.callback_query(F.data == "qa:save", QuickAddStates.awaiting_confirmation)
async def qa_save(cb: CallbackQuery, state, session, user: User):
    data = await state.get_data()
    if data.get("qa_action") == "transaction":
        try:
            tx, alerts = await TransactionService(session).create(
                user,
                type_=data["qa_type"],
                amount=Decimal(data["qa_amount"]),
                category_id=data["qa_category_id"],
                wallet_id=data["qa_wallet_id"],
                note=data.get("qa_note"),
                occurred_at=date.fromisoformat(data["qa_date"]) if data.get("qa_date") else today_local(),
                source=data.get("qa_source", "ai_text"),
                source_file_id=data.get("qa_source_file_id"),
            )
        except FreemiumBlockedError:
            await state.clear()
            draft_registry.unregister(user.id)
            await cb.message.edit_text(MSG_FREEMIUM_BLOCKED)
            return await cb.answer()
        except ValidationError as e:
            return await cb.answer(f"⚠️ {e}", show_alert=True)
        queue = data.get("qa_queue") or []
        if queue:
            # masih ada item berikutnya → tampilkan kartu berikutnya
            next_item = queue[0]
            await state.update_data(**next_item, qa_queue=queue[1:])
            await _render_card(cb.message.bot, cb.message.chat.id, state)
            await cb.answer(f"✅ Tersimpan ({data.get('qa_pos', 1)}/{data.get('qa_total', 1)})")
            for alert in alerts:
                await cb.message.answer(alert)
            return
        await state.clear()
        draft_registry.unregister(user.id)
        label, icon = ("Pemasukan", "💰") if data["qa_type"] == "income" else ("Pengeluaran", "💸")
        await cb.message.edit_text(
            f"✅ Tersimpan!\n{icon} {label} <b>{format_rupiah(tx.amount)}</b> — "
            f"{data['qa_category_name']} • {data['qa_wallet_name']}"
        )
        for alert in alerts:
            await cb.message.answer(alert)
    else:
        try:
            tf = await TransferService(session).create(
                user,
                from_wallet_id=data["qa_from_id"],
                to_wallet_id=data["qa_to_id"],
                amount=Decimal(data["qa_amount"]),
                note=data.get("qa_note"),
                occurred_at=date.fromisoformat(data["qa_date"]) if data.get("qa_date") else today_local(),
            )
        except ValidationError as e:
            return await cb.answer(f"⚠️ {e}", show_alert=True)
        await state.clear()
        draft_registry.unregister(user.id)
        await cb.message.edit_text(
            f"✅ Transfer tersimpan!\n{data['qa_from_name']} → {data['qa_to_name']}: "
            f"<b>{format_rupiah(tf.amount)}</b>"
        )
    await cb.answer()


@router.callback_query(F.data == "qa:cancel")
async def qa_cancel(cb: CallbackQuery, state, user: User):
    await state.clear()
    draft_registry.unregister(user.id)
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.callback_query(F.data == "qa:skip")
async def qa_skip(cb: CallbackQuery, state, user: User):
    """⏭️ Lewati item saat ini saja — lanjut ke item berikutnya di antrian multi."""
    data = await state.get_data()
    queue = data.get("qa_queue") or []
    if queue:
        next_item = queue[0]
        await state.update_data(**next_item, qa_queue=queue[1:])
        await _render_card(cb.message.bot, cb.message.chat.id, state)
        await cb.answer(f"⏭️ Item {data.get('qa_pos', 1)} dilewati")
        return
    # antrian habis (item terakhir dilewati) → tidak ada yang tersisa
    await state.clear()
    draft_registry.unregister(user.id)
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


# ====================== Koreksi kategori & wallet (list) ======================

async def _render_category_picker(cb: CallbackQuery, state, session, user: User, page: int):
    data = await state.get_data()
    categories = [c for c in await CategoryRepo(session).list_for_user(user.id)
                  if c.type == data["qa_type"]]
    total_pages = max(1, (len(categories) + CAT_PER_PAGE - 1) // CAT_PER_PAGE)
    page = min(max(page, 0), total_pages - 1)
    items = categories[page * CAT_PER_PAGE : (page + 1) * CAT_PER_PAGE]
    kb = category_list_kb(
        items, page, CAT_PER_PAGE, total_pages, page < total_pages - 1,
        select_prefix="qa2:c:", page_prefix="qa2:cpg:",
    )
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Batal", callback_data="qa2:cancel")])
    await render_step(cb.message.bot, cb.message.chat.id, state, "🏷️ Pilih kategori baru:", kb,
                      edit=True)


@router.callback_query(F.data == "qa:cat", QuickAddStates.awaiting_confirmation)
async def qa_correct_cat(cb: CallbackQuery, state, session, user: User):
    await _render_category_picker(cb, state, session, user, 0)
    await cb.answer()


@router.callback_query(F.data.startswith("qa2:cpg:"), QuickAddStates.awaiting_confirmation)
async def qa_cat_page(cb: CallbackQuery, state, session, user: User):
    await _render_category_picker(cb, state, session, user, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("qa2:c:"), QuickAddStates.awaiting_confirmation)
async def qa_cat_select(cb: CallbackQuery, state, session, user: User):
    cat_id = int(cb.data.split(":")[2])
    data = await state.get_data()
    category = await CategoryRepo(session).get_usable(cat_id, user.id)
    if not category or category.type != data["qa_type"]:
        return await cb.answer("Kategori tidak valid.", show_alert=True)
    await state.update_data(
        qa_category_id=category.id,
        qa_category_name=f"{category.icon or ''} {category.name}".strip(),
    )
    await _render_card(cb.message.bot, cb.message.chat.id, state)
    await cb.answer("Kategori diubah ✅")


async def _render_wallet_picker(cb: CallbackQuery, state, session, user: User,
                                select_prefix: str, exclude_id: int | None = None):
    wallets = [w for w in await WalletRepo(session).list_by_user(user.id, active_only=True)
               if w.id != exclude_id]
    kb = wallet_list_kb(wallets, select_prefix)
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Batal", callback_data="qa2:cancel")])
    await render_step(cb.message.bot, cb.message.chat.id, state, "👛 Pilih wallet:", kb,
                      edit=True)


@router.callback_query(F.data == "qa:wal", QuickAddStates.awaiting_confirmation)
async def qa_correct_wallet(cb: CallbackQuery, state, session, user: User):
    await _render_wallet_picker(cb, state, session, user, "qa2:w:")
    await cb.answer()


@router.callback_query(F.data.startswith("qa2:w:"), QuickAddStates.awaiting_confirmation)
async def qa_wallet_select(cb: CallbackQuery, state, session, user: User):
    wallet = await WalletRepo(session).get_for_user(int(cb.data.split(":")[2]), user.id)
    if not wallet or not wallet.is_active:
        return await cb.answer("Wallet tidak valid.", show_alert=True)
    await state.update_data(qa_wallet_id=wallet.id, qa_wallet_name=_name_with_icon(wallet))
    await _render_card(cb.message.bot, cb.message.chat.id, state)
    await cb.answer("Wallet diubah ✅")


@router.callback_query(F.data == "qa:from", QuickAddStates.awaiting_confirmation)
async def qa_correct_from(cb: CallbackQuery, state, session, user: User):
    await _render_wallet_picker(cb, state, session, user, "qa2:f:")
    await cb.answer()


@router.callback_query(F.data.startswith("qa2:f:"), QuickAddStates.awaiting_confirmation)
async def qa_from_select(cb: CallbackQuery, state, session, user: User):
    wallet = await WalletRepo(session).get_for_user(int(cb.data.split(":")[2]), user.id)
    if not wallet or not wallet.is_active:
        return await cb.answer("Wallet tidak valid.", show_alert=True)
    await state.update_data(qa_from_id=wallet.id, qa_from_name=_name_with_icon(wallet))
    await _render_card(cb.message.bot, cb.message.chat.id, state)
    await cb.answer("Wallet asal diubah ✅")


@router.callback_query(F.data == "qa:to", QuickAddStates.awaiting_confirmation)
async def qa_correct_to(cb: CallbackQuery, state, session, user: User):
    data = await state.get_data()
    await _render_wallet_picker(cb, state, session, user, "qa2:t:", exclude_id=data.get("qa_from_id"))
    await cb.answer()


@router.callback_query(F.data.startswith("qa2:t:"), QuickAddStates.awaiting_confirmation)
async def qa_to_select(cb: CallbackQuery, state, session, user: User):
    wallet = await WalletRepo(session).get_for_user(int(cb.data.split(":")[2]), user.id)
    if not wallet or not wallet.is_active:
        return await cb.answer("Wallet tidak valid.", show_alert=True)
    await state.update_data(qa_to_id=wallet.id, qa_to_name=_name_with_icon(wallet))
    await _render_card(cb.message.bot, cb.message.chat.id, state)
    await cb.answer("Wallet tujuan diubah ✅")


# ====================== Koreksi jumlah & catatan (free-text) ==================

@router.callback_query(F.data == "qa:amt", QuickAddStates.awaiting_confirmation)
async def qa_correct_amount(cb: CallbackQuery, state):
    await state.set_state(QuickAddCorrectionStates.correcting_amount)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "💰 Masukkan jumlah baru (contoh: 25000, 25.000, 25rb, 2jt):",
        ikb([[("❌ Batal", "qa2:cancel")]]),
        edit=True,
    )
    await cb.answer()


@router.message(QuickAddCorrectionStates.correcting_amount)
async def qa_enter_amount(message: Message, state):
    value = parse_amount(message.text)
    if value is None:
        await message.answer("⚠️ Format jumlah tidak dikenali. Contoh: 25000, 25.000, 25rb, 2jt")
        return
    await state.update_data(qa_amount=str(value))
    await state.set_state(QuickAddStates.awaiting_confirmation)
    await _render_card(message.bot, message.chat.id, state)


@router.callback_query(F.data == "qa:note", QuickAddStates.awaiting_confirmation)
async def qa_correct_note(cb: CallbackQuery, state):
    await state.set_state(QuickAddCorrectionStates.correcting_note)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "🗒️ Kirim catatan baru, atau tekan Hapus Catatan:",
        ikb([[("🗑 Hapus Catatan", "qa2:clearnote")], [("❌ Batal", "qa2:cancel")]]),
        edit=True,
    )
    await cb.answer()


@router.message(QuickAddCorrectionStates.correcting_note)
async def qa_enter_note(message: Message, state):
    await state.update_data(qa_note=message.text.strip()[:500])
    await state.set_state(QuickAddStates.awaiting_confirmation)
    await _render_card(message.bot, message.chat.id, state)


@router.callback_query(F.data == "qa2:clearnote", QuickAddCorrectionStates.correcting_note)
async def qa_clear_note(cb: CallbackQuery, state):
    await state.update_data(qa_note=None)
    await state.set_state(QuickAddStates.awaiting_confirmation)
    await _render_card(cb.message.bot, cb.message.chat.id, state)
    await cb.answer("Catatan dihapus ✅")


@router.callback_query(F.data == "qa2:cancel")
async def qa_correction_cancel(cb: CallbackQuery, state):
    await state.set_state(QuickAddStates.awaiting_confirmation)
    await _render_card(cb.message.bot, cb.message.chat.id, state)
    await cb.answer()


# ============================== Catch-all (paling akhir) ======================

@router.callback_query()
async def catch_all_callback(cb: CallbackQuery):
    """Callback tidak dikenal / kedaluwarsa → feedback singkat."""
    await cb.answer("Tombol ini sudah tidak berlaku.", show_alert=True)


@router.message()
async def catch_all_message(message: Message):
    await message.answer(
        "🙏 Aku belum paham tipe pesan ini. Kirim teks transaksi, foto struk, "
        "atau ketik /help."
    )
