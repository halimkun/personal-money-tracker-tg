"""Kelola kategori custom + keyword AI (PRD §4, §5.4).

Pola UX FSM (PRD §7): tiap prompt langkah pesan BARU; jawaban user ditempel
di prompt sebelumnya via `confirm_step`. Menu daftar kategori tetap di-update
di tempat.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.handlers.states import CategoryStates
from app.keyboards.inline import ikb
from app.repositories.categories import CategoryRepo
from app.services.categories import CategoryService
from app.services.errors import ValidationError
from app.utils.messages import confirm_step, edit_or_send, render_step

router = Router()

TYPE_LABELS = {"income": ("Pemasukan", "💰"), "expense": ("Pengeluaran", "💸")}


async def _render_menu(bot, chat_id: int, message_id: int | None, session, user: User):
    categories = await CategoryRepo(session).list_for_user(user.id)
    custom = await CategoryRepo(session).list_custom(user.id)
    lines = ["🏷️ <b>Kategori</b>", ""]
    for type_, (label, icon) in TYPE_LABELS.items():
        lines.append(f"{icon} <b>{label}</b>")
        for c in categories:
            if c.type != type_:
                continue
            suffix = ""
            if c.user_id is None:
                suffix = " <i>(bawaan)</i>"
            elif c.keywords:
                suffix = f" <i>(AI: {', '.join(c.keywords[:4])})</i>"
            lines.append(f"• {c.icon or ''} {c.name}{suffix}")
        lines.append("")
    lines.append("Keyword membantu AI mengenali transaksi, mis. kategori <i>Ngopi</i> "
                 "dengan keyword <i>kopi, starbucks, janji jiwa</i>.")
    kb = ikb([[("➕ Tambah Kategori", "cat:add")]])
    if custom:
        kb.inline_keyboard.append([_btn("🗑 Hapus Kategori", "cat:delmenu")])
    await edit_or_send(bot, chat_id, message_id, "\n".join(lines), kb)


def _btn(text: str, cb: str):
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text=text, callback_data=cb)


@router.message(Command("kategori"))
async def cmd_kategori(message: Message, session, user: User):
    await _render_menu(message.bot, message.chat.id, None, session, user)


@router.callback_query(F.data == "cat:back")
async def cat_back(cb: CallbackQuery, session, user: User):
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer()


@router.callback_query(F.data == "cat:cancel")
async def cat_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


# ============================== Hapus kategori ================================

@router.callback_query(F.data == "cat:delmenu")
async def cat_delmenu(cb: CallbackQuery, session, user: User):
    custom = await CategoryRepo(session).list_custom(user.id)
    rows = [[(f"{c.icon or '•'} {c.name}", f"cat:del:{c.id}")] for c in custom]
    rows.append([("⬅️ Kembali", "cat:back")])
    await cb.message.edit_text(
        "🗑 Pilih kategori custom yang mau dihapus (kategori bawaan tidak bisa dihapus):",
        reply_markup=ikb(rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cat:del:"))
async def cat_del_confirm(cb: CallbackQuery):
    cat_id = int(cb.data.split(":")[2])
    await cb.message.edit_text(
        "🗑 Yakin hapus kategori ini?\nKategori yang dipakai transaksi tidak bisa dihapus.",
        reply_markup=ikb([[("🗑 Hapus", f"cat:dely:{cat_id}"), ("❌ Batal", "cat:back")]]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cat:dely:"))
async def cat_del_execute(cb: CallbackQuery, session, user: User):
    cat_id = int(cb.data.split(":")[2])
    try:
        await CategoryService(session).delete(user.id, cat_id)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer("Kategori dihapus ✅")


# ============================== Tambah kategori ===============================

@router.callback_query(F.data == "cat:add")
async def cat_add(cb: CallbackQuery, state):
    await state.set_state(CategoryStates.choosing_type)
    # ingat pesan menu asal — di-refresh di tempat saat kategori selesai dibuat
    await state.update_data(menu_msg_id=cb.message.message_id)
    await render_step(
        cb.message.bot, cb.message.chat.id, state, "🏷️ Tipe kategori baru?",
        ikb([[("💸 Pengeluaran", "cat:t:expense"), ("💰 Pemasukan", "cat:t:income")],
             [("❌ Batal", "cat:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cat:t:"), CategoryStates.choosing_type)
async def cat_choose_type(cb: CallbackQuery, state):
    type_ = cb.data.split(":")[2]
    if type_ not in ("income", "expense"):
        return await cb.answer("Tipe tidak valid.", show_alert=True)
    await state.update_data(cat_type=type_)
    await state.set_state(CategoryStates.entering_name)
    label, icon = TYPE_LABELS[type_]
    await confirm_step(cb.message.bot, cb.message.chat.id, state,
                       f"Anda memilih: {icon} {label}")
    await render_step(
        cb.message.bot, cb.message.chat.id, state, "🏷️ Nama kategori (mis. <b>Ngopi</b>):",
        ikb([[("❌ Batal", "cat:cancel")]]),
    )
    await cb.answer()


@router.message(CategoryStates.entering_name)
async def cat_enter_name(message: Message, state):
    name = message.text.strip()[:100]
    await state.update_data(cat_name=name)
    await state.set_state(CategoryStates.entering_keywords)
    await confirm_step(message.bot, message.chat.id, state, f"🏷️ {name}")
    await render_step(
        message.bot, message.chat.id, state,
        "🔑 Keyword untuk AI (opsional, pisahkan dengan koma):\n"
        "contoh: <i>kopi, starbucks, janji jiwa</i>",
        ikb([[("⏭️ Lewati", "cat:skipkw")], [("❌ Batal", "cat:cancel")]]),
    )


@router.callback_query(F.data == "cat:skipkw", CategoryStates.entering_keywords)
async def cat_skip_keywords(cb: CallbackQuery, state, session, user: User):
    data = await state.get_data()
    try:
        await CategoryService(session).create(user.id, data["cat_name"], data["cat_type"], None)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await confirm_step(cb.message.bot, cb.message.chat.id, state, "⏭️ Tanpa keyword")
    await state.clear()
    await _render_menu(cb.message.bot, cb.message.chat.id, data.get("menu_msg_id"), session, user)
    await cb.answer("Kategori dibuat ✅")


@router.message(CategoryStates.entering_keywords)
async def cat_enter_keywords(message: Message, state, session, user: User):
    data = await state.get_data()
    try:
        await CategoryService(session).create(
            user.id, data["cat_name"], data["cat_type"], message.text
        )
    except ValidationError as e:
        await message.answer(f"⚠️ {e}")
        return
    await confirm_step(message.bot, message.chat.id, state,
                       f"🔑 {message.text.strip()[:100]}")
    await state.clear()
    await _render_menu(message.bot, message.chat.id, data.get("menu_msg_id"), session, user)
