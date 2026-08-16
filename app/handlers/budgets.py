"""Budget per kategori/total + alert pemakaian (PRD §5.1)."""

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from app.db.models import Budget, User
from app.domain.money import format_rupiah, parse_amount
from app.domain.periods import period_window
from app.handlers.states import BudgetStates
from app.keyboards.inline import ikb
from app.repositories.budgets import BudgetRepo
from app.repositories.categories import CategoryRepo
from app.services.budgets import BudgetService
from app.services.errors import ValidationError
from app.utils.format import fmt_date_short, today_local
from app.utils.messages import edit_or_send, render_step

router = Router()

PERIOD_LABELS = {"weekly": "Mingguan", "monthly": "Bulanan"}


def _btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)


async def _budget_row(session, b: Budget, usage: Decimal) -> str:
    label = "Budget total"
    if b.category_id:
        cat = await CategoryRepo(session).get(b.category_id)
        label = f"Budget {cat.name}" if cat else "Budget kategori"
    pct = usage / b.amount * 100 if b.amount else Decimal("0")
    status = "🟢" if not b.is_active else ("🔴" if pct >= 100 else "🟡" if pct >= b.alert_threshold_pct else "✅")
    start, end = period_window(b.period_type, today_local())
    return (
        f"{status} {label} ({PERIOD_LABELS.get(b.period_type, b.period_type)})\n"
        f"   {format_rupiah(usage)} / {format_rupiah(b.amount)} ({pct:.0f}%) · "
        f"{fmt_date_short(start)}–{fmt_date_short(end)}"
    )


async def _render_menu(bot, chat_id: int, message_id: int | None, session, user: User):
    items = await BudgetService(session).list_with_usage(user.id)
    if not items:
        lines = [
            "📊 <b>Budget</b>",
            "",
            "Belum ada budget. Budget membantumu membatasi pengeluaran — "
            "bot akan mengingatkan saat mendekati/melewati batas.",
        ]
        kb = ikb([[("➕ Buat Budget", "bg:add")]])
        await edit_or_send(bot, chat_id, message_id, "\n".join(lines), kb)
        return
    lines = ["📊 <b>Budget</b>", ""]
    rows = []
    for b, usage in items:
        lines.append(await _budget_row(session, b, usage))
        lines.append("")
        toggle = "⏸ Nonaktifkan" if b.is_active else "▶️ Aktifkan"
        rows.append([_btn(toggle, f"bg:toggle:{b.id}"), _btn("🗑 Hapus", f"bg:del:{b.id}")])
    rows.append([_btn("➕ Buat Budget", "bg:add")])
    await edit_or_send(bot, chat_id, message_id, "\n".join(lines), ikb(rows))


@router.message(Command("budget"))
async def cmd_budget(message: Message, session, user: User):
    await _render_menu(message.bot, message.chat.id, None, session, user)


@router.callback_query(F.data == "bg:cancel")
async def bg_cancel(cb: CallbackQuery, state):
    await state.clear()
    await cb.message.edit_text("❌ Dibatalkan.")
    await cb.answer()


@router.callback_query(F.data.startswith("bg:toggle:"))
async def bg_toggle(cb: CallbackQuery, session, user: User):
    budget_id = int(cb.data.split(":")[2])
    try:
        await BudgetService(session).toggle(user.id, budget_id)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer()


@router.callback_query(F.data.startswith("bg:del:"))
async def bg_del_confirm(cb: CallbackQuery):
    budget_id = int(cb.data.split(":")[2])
    await cb.message.edit_text(
        "🗑 Yakin hapus budget ini?",
        reply_markup=ikb([[("🗑 Hapus", f"bg:dely:{budget_id}"), ("❌ Batal", "bg:delno")]]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("bg:dely:"))
async def bg_del_execute(cb: CallbackQuery, session, user: User):
    budget_id = int(cb.data.split(":")[2])
    try:
        await BudgetService(session).delete(user.id, budget_id)
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer("Budget dihapus ✅")


@router.callback_query(F.data == "bg:delno")
async def bg_del_no(cb: CallbackQuery, session, user: User):
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer()


# ============================== Buat budget (FSM) =============================

@router.callback_query(F.data == "bg:add")
async def bg_add(cb: CallbackQuery, state):
    await state.set_state(BudgetStates.choosing_scope)
    await state.update_data(msg_id=None)
    await render_step(
        cb.message.bot, cb.message.chat.id, state, "📊 Budget untuk apa?",
        ikb([[("🌐 Total pengeluaran", "bg:scope:total")],
             [("🏷️ Per kategori", "bg:scope:cat")],
             [("❌ Batal", "bg:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data == "bg:scope:total", BudgetStates.choosing_scope)
async def bg_scope_total(cb: CallbackQuery, state):
    await state.update_data(budget_category_id=None)
    await state.set_state(BudgetStates.entering_amount)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        "💰 Jumlah budget total per periode (contoh: 1500000, 1,5jt):",
        ikb([[("❌ Batal", "bg:cancel")]]),
    )
    await cb.answer()


@router.callback_query(F.data == "bg:scope:cat", BudgetStates.choosing_scope)
async def bg_scope_cat(cb: CallbackQuery, state, session, user: User):
    await state.set_state(BudgetStates.choosing_category)
    await _render_budget_categories(cb.message, state, session, user, 0)
    await cb.answer()


async def _render_budget_categories(message, state, session, user: User, page: int):
    categories = [c for c in await CategoryRepo(session).list_for_user(user.id)
                  if c.type == "expense"]
    per_page = 10
    total_pages = max(1, (len(categories) + per_page - 1) // per_page)
    page = min(max(page, 0), total_pages - 1)
    items = categories[page * per_page : (page + 1) * per_page]
    rows = [[_btn(f"{c.icon or '•'} {c.name}", f"bg:c:{c.id}")] for c in items]
    nav = []
    if page > 0:
        nav.append(_btn("◀️", f"bg:cpg:{page - 1}"))
    if page < total_pages - 1:
        nav.append(_btn("▶️", f"bg:cpg:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_btn("❌ Batal", "bg:cancel")])
    await render_step(message.bot, message.chat.id, state, "🏷️ Budget untuk kategori mana?", ikb(rows))


@router.callback_query(F.data.startswith("bg:cpg:"), BudgetStates.choosing_category)
async def bg_category_page(cb: CallbackQuery, state, session, user: User):
    await _render_budget_categories(cb.message, state, session, user, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("bg:c:"), BudgetStates.choosing_category)
async def bg_choose_category(cb: CallbackQuery, state, session, user: User):
    category = await CategoryRepo(session).get_usable(int(cb.data.split(":")[2]), user.id)
    if not category or category.type != "expense":
        return await cb.answer("Kategori tidak valid.", show_alert=True)
    await state.update_data(budget_category_id=category.id)
    await state.set_state(BudgetStates.entering_amount)
    await render_step(
        cb.message.bot, cb.message.chat.id, state,
        f"💰 Jumlah budget <b>{category.name}</b> per periode (contoh: 500000, 500rb):",
        ikb([[("❌ Batal", "bg:cancel")]]),
    )
    await cb.answer()


@router.message(BudgetStates.entering_amount)
async def bg_enter_amount(message: Message, state):
    value = parse_amount(message.text)
    if value is None:
        await message.answer("⚠️ Format jumlah tidak dikenali. Contoh: 500000, 500rb, 1,5jt")
        return
    await state.update_data(budget_amount=str(value))
    await state.set_state(BudgetStates.choosing_period)
    await render_step(
        message.bot, message.chat.id, state, "📅 Periode budget?",
        ikb([[("📆 Mingguan", "bg:per:weekly"), ("🗓️ Bulanan", "bg:per:monthly")],
             [("❌ Batal", "bg:cancel")]]),
    )


@router.callback_query(F.data.startswith("bg:per:"), BudgetStates.choosing_period)
async def bg_choose_period(cb: CallbackQuery, state, session, user: User):
    period = cb.data.split(":")[2]
    data = await state.get_data()
    try:
        await BudgetService(session).create(
            user.id,
            category_id=data.get("budget_category_id"),
            wallet_id=None,
            period_type=period,
            amount=Decimal(data["budget_amount"]),
        )
    except ValidationError as e:
        return await cb.answer(f"⚠️ {e}", show_alert=True)
    await state.clear()
    await _render_menu(cb.message.bot, cb.message.chat.id, cb.message.message_id, session, user)
    await cb.answer("Budget dibuat ✅")
