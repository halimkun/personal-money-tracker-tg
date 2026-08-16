"""Panel admin (PRD §5.3 & §6): stats, user, pembayaran, broadcast, konfigurasi.

Keamanan: setiap handler cek `is_admin`; callback token `ap:` juga divalidasi
ganda (kepemilikan token + admin). Semua perubahan config tercatat di admin_logs.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.ai.client import clear_cache
from app.config import settings
from app.db.models import User
from app.domain.money import format_rupiah, parse_amount
from app.handlers.states import AdminInputStates, BroadcastStates
from app.keyboards.inline import ikb
from app.repositories.payments import PaymentRepo
from app.repositories.users import UserRepo
from app.services.callback_refs import CallbackRefService
from app.services.errors import ValidationError
from app.services.payments import PaymentService
from app.services.settings import SettingsService
from app.services.stats import build_stats_text
from app.services.users import UserService
from app.utils.format import fmt_datetime, today_local
from app.utils.messages import edit_or_send, render_step

router = Router()

PER_PAGE = 10


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_set


def _btn(text: str, cb: str):
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text=text, callback_data=cb)


def _mask_key(key: str) -> str:
    return (key[:4] + "…" + key[-4:]) if len(key) > 8 else ("(ada)" if key else "(kosong)")


# ============================== Command =======================================

@router.message(Command("admin"))
async def cmd_admin(message: Message, session, user: User):
    if not is_admin(user.telegram_id):
        return
    svc = SettingsService(session)
    lines = [
        "🛠️ <b>Panel Admin</b>",
        "",
        f"Mode berbayar: {'🔴 aktif' if await svc.payment_required() else '🟢 nonaktif'} · "
        f"kuota free: {await svc.free_limit()}/bulan",
        f"Insight AI global: {'🟢' if await svc.insight_enabled_global() else '🔴'}",
        "",
        "Pilih menu:",
    ]
    kb = ikb([
        [("📊 Statistik", "adm:stats"), ("👥 Daftar User", "adm:users:0")],
        [("💳 Pembayaran Pending", "adm:pending")],
        [("📢 Broadcast", "adm:broadcast")],
        [("🤖 Konfigurasi AI", "adm:setai")],
        [("⚙️ Pengaturan Sistem", "adm:sett")],
    ])
    await edit_or_send(message.bot, message.chat.id, None, "\n".join(lines), kb)


@router.message(Command("stats"))
async def cmd_stats(message: Message, session, user: User):
    if not is_admin(user.telegram_id):
        return
    await message.answer(await build_stats_text(session))


@router.message(Command("grantpremium"))
async def cmd_grantpremium(message: Message, session, user: User):
    if not is_admin(user.telegram_id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Pakai: /grantpremium &lt;telegram_id&gt;")
        return
    target = await UserRepo(session).get_by_telegram_id(int(parts[1]))
    if not target:
        await message.answer("User tidak ditemukan (pastikan sudah pernah /start).")
        return
    await UserService(session).grant_premium(target, None)
    await message.answer(f"⭐ {target.full_name or target.telegram_id} kini premium seumur hidup.")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state, user: User):
    if not is_admin(user.telegram_id):
        return
    await state.set_state(BroadcastStates.entering_text)
    await state.update_data(msg_id=None)
    await render_step(
        message.bot, message.chat.id, state,
        "📢 Kirim teks broadcast (akan dikirim ke semua user aktif). Ketik /cancel untuk batal.",
        ikb([[("❌ Batal", "adm:bccancel")]]),
    )


# ============================== Callback menu =================================

@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await cb.message.edit_text(await build_stats_text(session))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:users:"))
async def adm_users(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    page = int(cb.data.split(":")[2])
    users, total = await UserRepo(session).list_paginated(page, PER_PAGE)
    if not users:
        return await cb.answer("Tidak ada user.", show_alert=True)
    lines = [f"👥 <b>Daftar User</b> ({total})", ""]
    rows = []
    for u in users:
        premium = "⭐" if u.is_premium else ""
        blocked = f" · 🚫 {u.free_transaction_count}" if not u.is_premium else ""
        lines.append(
            f"{u.id}. {u.full_name or '—'} (@{u.username or '—'}) {premium}{blocked}\n"
            f"    tg {u.telegram_id} · aktif: {'✅' if u.is_active else '❌'}"
        )
        rows.append([(f"{u.id}. {u.full_name or u.telegram_id}", f"adm:user:{u.id}")])
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    lines.append(f"\nHal. {page + 1}/{total_pages}")
    nav = []
    if page > 0:
        nav.append(_btn("◀️", f"adm:users:{page - 1}"))
    if page < total_pages - 1:
        nav.append(_btn("▶️", f"adm:users:{page + 1}"))
    if nav:
        rows.append(nav)
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:user:"))
async def adm_user_detail(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    target = await UserRepo(session).get(int(cb.data.split(":")[2]))
    if not target:
        return await cb.answer("User tidak ditemukan.", show_alert=True)
    premium = "seumur hidup ♾️" if target.premium_until is None else f"s.d. {fmt_datetime(target.premium_until)}"
    lines = [
        f"👤 <b>{target.full_name or '—'}</b>",
        f"Telegram: {target.telegram_id} (@{target.username or '—'})",
        f"Premium: {'⭐ ' + premium if target.is_premium else '❌ Free'}",
        f"Kuota free terpakai: {target.free_transaction_count}",
        f"Insight AI: {'🟢' if target.ai_insight_enabled else '🔴'}",
        f"Aktif: {'✅' if target.is_active else '❌'} · terdaftar {fmt_datetime(target.created_at)}",
    ]
    rows = []
    if not target.is_premium:
        rows.append([_btn("⭐ Grant Premium (seumur hidup)", f"adm:grant:{target.id}")])
    rows.append([_btn("⬅️ Kembali", "adm:users:0")])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:grant:"))
async def adm_grant(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    target = await UserRepo(session).get(int(cb.data.split(":")[2]))
    if not target:
        return await cb.answer("User tidak ditemukan.", show_alert=True)
    await UserService(session).grant_premium(target, None)
    await cb.answer(f"⭐ {target.full_name or target.telegram_id} premium seumur hidup ✅")
    await adm_user_detail(cb, session, user)


@router.callback_query(F.data == "adm:pending")
async def adm_pending(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    items = await PaymentRepo(session).list_pending()
    if not items:
        await cb.message.edit_text("💳 Tidak ada pembayaran pending. 🎉")
        return await cb.answer()
    token_svc = CallbackRefService(session)
    lines = [f"💳 <b>Pembayaran Pending</b> ({len(items)})", ""]
    rows = []
    for p, username in items:
        buyer = await UserRepo(session).get(p.user_id)
        name = buyer.full_name if buyer else "?"
        lines.append(
            f"#{p.id} · {name} (@{username or '—'}) — {format_rupiah(p.amount)}\n"
            f"    {fmt_datetime(p.created_at)}"
        )
        # token dibuat untuk admin yang sedang menekan (PRD §7c)
        approve_token = await token_svc.create(user.telegram_id, "payment_decision",
                                               {"payment_id": p.id, "action": "approve"})
        reject_token = await token_svc.create(user.telegram_id, "payment_decision",
                                              {"payment_id": p.id, "action": "reject"})
        rows.append([
            (f"✅ #{p.id}", f"ap:{approve_token}"),
            (f"❌ #{p.id}", f"ap:{reject_token}"),
        ])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("ap:"))
async def ap_decision(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    payload = await CallbackRefService(session).resolve(cb.data[3:], user.telegram_id)
    if payload is None or payload["purpose"] != "payment_decision":
        return await cb.answer("Tombol kedaluwarsa/tidak valid.", show_alert=True)
    payment = await PaymentRepo(session).get(payload["payment_id"])
    if not payment:
        return await cb.answer("Pembayaran tidak ditemukan.", show_alert=True)
    action = payload["action"]
    try:
        if action == "approve":
            buyer = await PaymentService(session).approve(payment, user.telegram_id)
        else:
            buyer = await PaymentService(session).reject(payment, user.telegram_id)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)

    if buyer:
        try:
            if action == "approve":
                await cb.message.bot.send_message(
                    buyer.telegram_id,
                    "🎉 Pembayaran premium kamu <b>disetujui</b>! "
                    "Fitur premium sudah aktif — cek /status.",
                )
            else:
                await cb.message.bot.send_message(
                    buyer.telegram_id,
                    "❌ Maaf, pembayaran premium kamu ditolak. "
                    "Hubungi admin untuk info lebih lanjut.",
                )
        except Exception:
            pass
    status = "✅ DISETUJUI" if action == "approve" else "❌ DITOLAK"
    await cb.message.edit_text(f"{cb.message.html_text}\n\n⏹ Pembayaran #{payment.id}: {status}")
    await cb.answer("Diproses ✅")


# ============================== Broadcast =====================================

@router.callback_query(F.data == "adm:bccancel")
async def adm_bc_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Broadcast dibatalkan.")
    await cb.answer()


@router.message(BroadcastStates.entering_text)
async def adm_bc_text(message: Message, state):
    text = message.text.strip()
    if not text:
        await message.answer("Teks tidak boleh kosong.")
        return
    await state.update_data(broadcast_text=text)
    await render_step(
        message.bot, message.chat.id, state,
        f"📢 <b>Pratinjau broadcast:</b>\n\n{text[:2000]}\n\nKirim ke semua user aktif?",
        ikb([[("🚀 Kirim", "adm:bcsend"), ("❌ Batal", "adm:bccancel")]]),
    )


@router.callback_query(F.data == "adm:bcsend")
async def adm_bc_send(cb: CallbackQuery, state, session):
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    if not text:
        return await cb.answer("Tidak ada teks.", show_alert=True)
    users = await UserRepo(session).list_active()
    sent, failed = 0, 0
    for u in users:
        try:
            await cb.message.bot.send_message(u.telegram_id, text)
            sent += 1
        except Exception:
            failed += 1
    await state.clear()
    await cb.message.edit_text(f"📢 Broadcast selesai: ✅ {sent} terkirim, ❌ {failed} gagal.")
    await cb.answer()


# ============================== Konfigurasi AI ================================

@router.callback_query(F.data == "adm:setai")
async def adm_setai_menu(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    svc = SettingsService(session)
    cfg = await svc.ai_config()
    lines = [
        "🤖 <b>Konfigurasi AI</b>",
        "",
        f"API Key: {_mask_key(cfg['api_key'])}",
        f"Base URL: {cfg['base_url']}",
        f"Model: {cfg['model']}",
        f"Kuota harian per user: {await svc.ai_daily_limit()}",
        "",
        "Catatan: bot otomatis fallback ke teks manual (/catat) tanpa AI "
        "kalau API key kosong (PRD §5.1b poin 2).",
    ]
    kb = ikb([
        [("🔑 Ganti API Key", "adm:setkey"), ("🔗 Ganti Base URL", "adm:seturl")],
        [("🧠 Ganti Model", "adm:setmodel"), ("⏳ Kuota Harian", "adm:setlimit")],
        [("⬅️ Kembali", "adm:back")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:back")
async def adm_back(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await cmd_admin(cb.message, session, user)
    await cb.answer()


async def _prompt_input(cb: CallbackQuery, state, target_state, prompt: str):
    await state.set_state(target_state)
    await state.update_data(msg_id=None)
    await render_step(cb.message.bot, cb.message.chat.id, state, prompt,
                      ikb([[("❌ Batal", "adm:cancel")]]))
    await cb.answer()


@router.callback_query(F.data == "adm:setkey")
async def adm_set_key(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_api_key,
                        "🔑 Kirim API key baru (mis. sk-...). Kosongkan dengan kirim <b>-</b>.")


@router.callback_query(F.data == "adm:seturl")
async def adm_set_url(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_base_url,
                        "🔗 Kirim base URL (mis. https://api.openai.com/v1):")


@router.callback_query(F.data == "adm:setmodel")
async def adm_set_model(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_model,
                        "🧠 Kirim nama model (mis. gpt-4o-mini):")


@router.callback_query(F.data == "adm:setlimit")
async def adm_set_limit(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_daily_limit,
                        "⏳ Kirim kuota harian AI per user (angka, mis. 30):")


@router.callback_query(F.data == "adm:cancel")
async def adm_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.message(AdminInputStates.entering_api_key)
async def adm_input_key(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    value = "" if message.text.strip() == "-" else message.text.strip()
    await SettingsService(session).set_ai_api_key(value, user.telegram_id)
    clear_cache()
    await state.clear()
    await message.answer("🔑 API key tersimpan (terenkripsi).")
    await _rerender_setai(message, session, user)


@router.message(AdminInputStates.entering_base_url)
async def adm_input_url(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    await SettingsService(session).set("ai_base_url", message.text.strip(), user.telegram_id)
    clear_cache()
    await state.clear()
    await message.answer("🔗 Base URL tersimpan.")
    await _rerender_setai(message, session, user)


@router.message(AdminInputStates.entering_model)
async def adm_input_model(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    await SettingsService(session).set("ai_model", message.text.strip(), user.telegram_id)
    clear_cache()
    await state.clear()
    await message.answer("🧠 Model tersimpan.")
    await _rerender_setai(message, session, user)


@router.message(AdminInputStates.entering_daily_limit)
async def adm_input_limit(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    try:
        limit = int(message.text.strip())
        if limit < 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Kirim angka saja (mis. 30).")
        return
    await SettingsService(session).set("ai_daily_limit", str(limit), user.telegram_id)
    await state.clear()
    await message.answer(f"⏳ Kuota harian AI: {limit}.")
    await _rerender_setai(message, session, user)


async def _rerender_setai(message: Message, session, user: User):
    svc = SettingsService(session)
    cfg = await svc.ai_config()
    lines = [
        "🤖 <b>Konfigurasi AI</b>",
        "",
        f"API Key: {_mask_key(cfg['api_key'])}",
        f"Base URL: {cfg['base_url']}",
        f"Model: {cfg['model']}",
        f"Kuota harian per user: {await svc.ai_daily_limit()}",
        "",
        "Catatan: bot otomatis fallback ke teks manual (/catat) tanpa AI "
        "kalau API key kosong (PRD §5.1b poin 2).",
    ]
    kb = ikb([
        [("🔑 Ganti API Key", "adm:setkey"), ("🔗 Ganti Base URL", "adm:seturl")],
        [("🧠 Ganti Model", "adm:setmodel"), ("⏳ Kuota Harian", "adm:setlimit")],
        [("⬅️ Kembali", "adm:back")],
    ])
    await edit_or_send(message.bot, message.chat.id, None, "\n".join(lines), kb)


# ============================== Pengaturan sistem =============================

@router.callback_query(F.data == "adm:sett")
async def adm_sett_menu(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    svc = SettingsService(session)
    price = await svc.premium_price()
    days = await svc.premium_duration_days()
    lines = [
        "⚙️ <b>Pengaturan Sistem</b>",
        "",
        f"Mode berbayar: {'🔴 aktif' if await svc.payment_required() else '🟢 nonaktif'}",
        f"Kuota free: {await svc.free_limit()} transaksi/bulan",
        f"Insight AI global: {'🟢' if await svc.insight_enabled_global() else '🔴'}",
        f"Harga premium: {format_rupiah(price)} / {days} hari",
        f"Instruksi bayar: {await svc.payment_instructions()}",
    ]
    kb = ikb([
        [("💳 Toggle Mode Berbayar", "adm:toggleq"),
         ("🧠 Toggle Insight Global", "adm:tinsglobal")],
        [("🔢 Kuota Free", "adm:setfl"), ("💰 Harga Premium", "adm:setprice")],
        [("📝 Instruksi Bayar", "adm:setinstr")],
        [("⬅️ Kembali", "adm:back")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:toggleq")
async def adm_toggle_payreq(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    svc = SettingsService(session)
    new_val = "false" if await svc.payment_required() else "true"
    await svc.set("payment_required", new_val, user.telegram_id)
    await adm_sett_menu(cb, session, user)
    await cb.answer("Mode berbayar diubah")


@router.callback_query(F.data == "adm:tinsglobal")
async def adm_toggle_insight(cb: CallbackQuery, session, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    svc = SettingsService(session)
    new_val = "false" if await svc.insight_enabled_global() else "true"
    await svc.set("ai_insight_enabled_global", new_val, user.telegram_id)
    await adm_sett_menu(cb, session, user)
    await cb.answer("Insight AI global diubah")


@router.callback_query(F.data == "adm:setfl")
async def adm_set_freelimit(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_free_limit,
                        "🔢 Kirim kuota transaksi gratis per bulan (angka, mis. 200):")


@router.callback_query(F.data == "adm:setprice")
async def adm_set_price(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_price,
                        "💰 Kirim harga premium (mis. 50000 atau 50rb):")


@router.callback_query(F.data == "adm:setinstr")
async def adm_set_instr(cb: CallbackQuery, state, user: User):
    if not is_admin(user.telegram_id):
        return await cb.answer("Akses ditolak.", show_alert=True)
    await _prompt_input(cb, state, AdminInputStates.entering_instructions,
                        "📝 Kirim instruksi pembayaran (teks bebas):")


@router.message(AdminInputStates.entering_free_limit)
async def adm_input_freelimit(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    try:
        limit = int(message.text.strip())
        if limit < 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Kirim angka saja (mis. 200).")
        return
    await SettingsService(session).set("free_transaction_limit", str(limit), user.telegram_id)
    await state.clear()
    await message.answer(f"🔢 Kuota free: {limit}/bulan.")
    await _rerender_sett(message, session, user)


@router.message(AdminInputStates.entering_price)
async def adm_input_price(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    price = parse_amount(message.text)
    if price is None or price <= 0:
        await message.answer("⚠️ Format harga tidak dikenali. Contoh: 50000, 50rb.")
        return
    await SettingsService(session).set("premium_price", str(price), user.telegram_id)
    await state.clear()
    await message.answer(f"💰 Harga premium: {format_rupiah(price)}.")
    await _rerender_sett(message, session, user)


@router.message(AdminInputStates.entering_instructions)
async def adm_input_instr(message: Message, state, session, user: User):
    if not is_admin(user.telegram_id):
        return
    await SettingsService(session).set("payment_instructions", message.text.strip(), user.telegram_id)
    await state.clear()
    await message.answer("📝 Instruksi pembayaran tersimpan.")
    await _rerender_sett(message, session, user)


async def _rerender_sett(message: Message, session, user: User):
    svc = SettingsService(session)
    price = await svc.premium_price()
    days = await svc.premium_duration_days()
    lines = [
        "⚙️ <b>Pengaturan Sistem</b>",
        "",
        f"Mode berbayar: {'🔴 aktif' if await svc.payment_required() else '🟢 nonaktif'}",
        f"Kuota free: {await svc.free_limit()} transaksi/bulan",
        f"Insight AI global: {'🟢' if await svc.insight_enabled_global() else '🔴'}",
        f"Harga premium: {format_rupiah(price)} / {days} hari",
        f"Instruksi bayar: {await svc.payment_instructions()}",
    ]
    kb = ikb([
        [("💳 Toggle Mode Berbayar", "adm:toggleq"),
         ("🧠 Toggle Insight Global", "adm:tinsglobal")],
        [("🔢 Kuota Free", "adm:setfl"), ("💰 Harga Premium", "adm:setprice")],
        [("📝 Instruksi Bayar", "adm:setinstr")],
        [("⬅️ Kembali", "adm:back")],
    ])
    await edit_or_send(message.bot, message.chat.id, None, "\n".join(lines), kb)
