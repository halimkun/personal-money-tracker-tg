def paginate(items: list, page: int, per_page: int) -> tuple[list, int, bool]:
    """Return (items_halaman_ini, total_halaman, has_next)."""
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return items[start : start + per_page], total_pages, page < total_pages - 1
