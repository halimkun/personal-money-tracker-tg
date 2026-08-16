"""Statistik global untuk admin (/stats) — PRD §5.2."""

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.domain.periods import month_label, month_window
from app.repositories.payments import PaymentRepo
from app.repositories.transactions import TransactionRepo
from app.repositories.transfers import TransferRepo
from app.repositories.users import UserRepo
from app.services.settings import SettingsService
from app.utils.format import today_local


async def db_size_estimate(session: AsyncSession) -> int | None:
    """Estimasi ukuran DB dalam byte."""
    url = app_settings.database_url
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if os.path.exists(path):
            return os.path.getsize(path)
        return None
    try:
        row = await session.scalar(text("SELECT pg_database_size(current_database())"))
        return int(row) if row else None
    except Exception:
        return None


def _fmt_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "n/a"
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


async def gather_stats(session: AsyncSession) -> dict:
    user_repo = UserRepo(session)
    tx_repo = TransactionRepo(session)
    tr_repo = TransferRepo(session)
    today = today_local()
    start, end = month_window(today)
    month_key = month_label(today)

    settings_svc = SettingsService(session)
    ai_counters = await settings_svc.ai_month_counters(month_key)

    return {
        "total_users": await user_repo.count(),
        "active_users": await user_repo.count_active(),
        "premium_users": await user_repo.count_premium(),
        "total_transactions": await tx_repo.count_all(),
        "month_transactions": await tx_repo.count_all_in_window(start, end),
        "total_transfers": await tr_repo.count_all(),
        "pending_payments": await PaymentRepo(session).count_pending(),
        "ai_calls": ai_counters["calls"],
        "ai_prompt_tokens": ai_counters["prompt_tokens"],
        "ai_completion_tokens": ai_counters["completion_tokens"],
        "db_size_bytes": await db_size_estimate(session),
        "payment_required": await settings_svc.payment_required(),
    }


async def build_stats_text(session: AsyncSession) -> str:
    s = await gather_stats(session)
    settings_svc = SettingsService(session)
    lines = [
        "📊 <b>Statistik Global</b>",
        "",
        f"👥 User: {s['total_users']} (aktif {s['active_users']}, premium {s['premium_users']})",
        f"💳 Transaksi: {s['total_transactions']} total, {s['month_transactions']} bulan ini",
        f"🔁 Transfer: {s['total_transfers']}",
        f"💳 Pembayaran pending: {s['pending_payments']}",
        "",
        f"🤖 AI calls bulan ini: {s['ai_calls']}",
        f"   Token: {s['ai_prompt_tokens']:,} in / {s['ai_completion_tokens']:,} out",
    ]
    price_per_1m = await settings_svc.ai_price_per_1m()
    if price_per_1m:
        total_tokens = s["ai_prompt_tokens"] + s["ai_completion_tokens"]
        est = total_tokens / 1_000_000 * price_per_1m
        lines.append(f"   Estimasi biaya AI: Rp {est:,.0f}")
    lines.append("")
    lines.append(f"💾 Estimasi ukuran DB: {_fmt_size(s['db_size_bytes'])}")
    lines.append(f"💰 Monetisasi: {'AKTIF' if s['payment_required'] else 'nonaktif'}")
    return "\n".join(lines)
