"""Job APScheduler (PRD §2 & §5.4): insight bulanan, reset kuota, cleanup token, expiry draft."""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from app.config import settings
from app.repositories.callback_refs import CallbackRefRepo
from app.repositories.insights import InsightRepo
from app.repositories.users import UserRepo
from app.scheduler.drafts import draft_registry
from app.services.settings import SettingsService
from app.services.summary import SummaryService
from app.utils.format import today_local

log = logging.getLogger(__name__)

DRAFT_EXPIRED_TEXT = "⌛ Draft kadaluarsa. Kirim ulang kalau masih ingin dicatat."


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def setup_scheduler(scheduler, *, bot: Bot, storage, session_factory) -> None:
    scheduler.add_job(cleanup_callback_refs, "cron", minute=15, args=[session_factory])
    scheduler.add_job(expire_quick_add_drafts, "interval", minutes=1,
                      args=[bot, storage, session_factory])
    scheduler.add_job(reset_monthly_counters, "cron", day=1, hour=0, minute=5,
                      args=[session_factory])
    scheduler.add_job(expire_premiums_job, "cron", hour=0, minute=10, args=[session_factory])
    scheduler.add_job(monthly_ai_insights, "cron", day=1, hour=8, minute=0,
                      args=[bot, session_factory])


async def cleanup_callback_refs(session_factory) -> None:
    """Hapus callback token kedaluwarsa/terpakai (PRD §7c housekeeping)."""
    try:
        async with session_factory() as s:
            removed = await CallbackRefRepo(s).cleanup(_now_utc() - timedelta(days=1))
            if removed:
                log.info("cleanup_callback_refs: %d token dihapus", removed)
    except Exception:
        log.exception("cleanup_callback_refs gagal")


async def expire_quick_add_drafts(bot: Bot, storage, session_factory) -> None:
    """Auto-expire kartu konfirmasi quick-add (PRD §5.1b poin 6)."""
    now = _now_utc()
    for entry in draft_registry.snapshot():
        if entry.expires_at > now:
            continue
        draft_registry.unregister(entry.user_id)
        try:
            ctx = FSMContext(
                storage,
                StorageKey(bot_id=bot.id, chat_id=entry.chat_id, user_id=entry.user_id),
            )
            await ctx.clear()
            await bot.edit_message_text(
                DRAFT_EXPIRED_TEXT, chat_id=entry.chat_id, message_id=entry.message_id
            )
        except Exception:
            log.exception("expire draft user=%s gagal", entry.user_id)


async def reset_monthly_counters(session_factory) -> None:
    """Reset kuota transaksi gratis tiap bulan (PRD §3 diagram)."""
    try:
        async with session_factory() as s:
            await UserRepo(s).reset_free_counters()
            log.info("reset_monthly_counters selesai")
    except Exception:
        log.exception("reset_monthly_counters gagal")


async def expire_premiums_job(session_factory) -> None:
    try:
        async with session_factory() as s:
            n = await UserRepo(s).expire_premiums(_now_utc())
            if n:
                log.info("expire_premiums: %d user diturunkan", n)
    except Exception:
        log.exception("expire_premiums gagal")


async def monthly_ai_insights(bot: Bot, session_factory) -> None:
    """Generate insight bulan lalu untuk user yang eligible (PRD §5.4)."""
    async with session_factory() as s:
        settings_svc = SettingsService(s)
        if not await settings_svc.insight_enabled_global():
            log.info("monthly_ai_insights: fitur dinonaktifkan global, skip")
            return
        from app.domain.periods import month_label, previous_month

        month_date = previous_month(today_local())
        label = month_label(month_date)
        users = await UserRepo(s).list_insight_recipients()
        for user in users:
            try:
                agg = await SummaryService(s).month_aggregates(user.id, month_date)
                if agg["tx_count"] == 0:
                    continue
                from app.ai import insight as ai_insight

                content = await ai_insight.generate(s, user.id, agg)
                await InsightRepo(s).create(user.id, label, content)
                await bot.send_message(
                    user.telegram_id,
                    f"✨ <b>Insight keuangan {label}</b> sudah siap!\n\n{content}",
                )
            except Exception:
                log.exception("insight bulanan gagal untuk user=%s", user.telegram_id)
