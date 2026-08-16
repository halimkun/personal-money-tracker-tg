"""Builder inline keyboard (PRD §7: callback_data pendek, di bawah 64 byte)."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def ikb(buttons: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """Helper: list baris berisi (teks, callback_data) → InlineKeyboardMarkup."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=c) for t, c in row] for row in buttons
        ]
    )


def back_kb(back_cb: str) -> InlineKeyboardMarkup:
    return ikb([[("⬅️ Kembali", back_cb)]])


# -- Kategori -----------------------------------------------------------------

def category_list_kb(
    categories, page: int, per_page: int, total_pages: int, has_next: bool,
    select_prefix: str, page_prefix: str,
) -> InlineKeyboardMarkup:
    from app.utils.pagination import paginate

    rows: list[list[tuple[str, str]]] = []
    items, _, _ = paginate(list(categories), page, per_page)
    for i in range(0, len(items), 2):
        row = [
            (
                f"{c.icon or '•'} {c.name}",
                f"{select_prefix}{c.id}",
            )
            for c in items[i : i + 2]
        ]
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(("◀️", f"{page_prefix}{page - 1}"))
    if has_next:
        nav.append(("▶️", f"{page_prefix}{page + 1}"))
    if nav:
        rows.append(nav)
    return ikb(rows)


def wallet_list_kb(wallets, select_prefix: str, show_balance: bool = False,
                   balance_lines: dict | None = None) -> InlineKeyboardMarkup:
    from app.domain.enums import WALLET_TYPE_ICONS
    from app.domain.money import format_rupiah

    rows = []
    for w in wallets:
        icon = WALLET_TYPE_ICONS.get(w.type, "💼")
        text = f"{icon} {w.name}"
        if show_balance and balance_lines:
            text += f" · {format_rupiah(balance_lines.get(w.id, 0))}"
        rows.append([(text, f"{select_prefix}{w.id}")])
    return ikb(rows)


# -- Quick-add card -----------------------------------------------------------

def quick_add_card_kb(kind: str) -> InlineKeyboardMarkup:
    """Kartu konfirmasi quick-add (PRD §5.1b poin 5)."""
    rows: list[list[tuple[str, str]]] = []
    if kind == "transaction":
        rows.append([("✏️ Ubah Kategori", "qa:cat"), ("✏️ Ubah Wallet", "qa:wal")])
    else:
        rows.append([("✏️ Ubah Dari", "qa:from"), ("✏️ Ubah Ke", "qa:to")])
    rows.append([("✏️ Ubah Jumlah", "qa:amt"), ("✏️ Ubah Catatan", "qa:note")])
    rows.append([("✅ Simpan", "qa:save"), ("❌ Batal", "qa:cancel")])
    return ikb(rows)


def quick_add_cancel_kb() -> InlineKeyboardMarkup:
    return ikb([[("❌ Batal", "qa:cancel")]])
