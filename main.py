"""MoneyBot — entry point.

Lapisan arsitektur:
    handlers (presentasi aiogram) → services (orkestrasi) → repositories (data)
    → domain (logika murni). Infrastruktur: middlewares, ai/, scheduler/.

Jalankan:
    uv run python main.py            # mode polling (default)
    uv run python -m alembic upgrade head   # migrasi DB dulu (sekali)
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db.session import session_factory
from app.handlers import register_all_routers
from app.middlewares.db_session import DbSessionMiddleware
from app.middlewares.locking import LockingMiddleware
from app.middlewares.registration import RegistrationMiddleware
from app.services.seed import seed_global_categories

log = logging.getLogger("moneybot")


def build_storage():
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    log.warning("REDIS_URL kosong — pakai MemoryStorage (cukup untuk dev; produksi pakai Redis)")
    return MemoryStorage()


def build_dispatcher(storage) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    dp["session_factory"] = session_factory
    # Urutan registrasi = urutan lapisan middleware (pertama = terluar)
    dp.update.middleware(DbSessionMiddleware())       # 1 sesi DB per update
    dp.update.middleware(RegistrationMiddleware())    # cek user terdaftar
    dp.update.middleware(LockingMiddleware())         # State Locking Policy (PRD §7b)
    register_all_routers(dp)
    return dp


async def on_startup() -> None:
    """Seed kategori global (idempoten) — wajib sebelum quick-add AI dipakai."""
    async with session_factory() as session:
        await seed_global_categories(session)
        await session.commit()
    log.info("seed kategori global selesai")


async def run_polling(bot: Bot, dp: Dispatcher, storage) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await on_startup()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    from app.scheduler.jobs import setup_scheduler

    setup_scheduler(scheduler, bot=bot, storage=storage, session_factory=session_factory)
    scheduler.start()
    log.info("bot polling mulai (mode: %s)", settings.bot_mode)
    await dp.start_polling(bot)


async def run_webhook(bot: Bot, dp: Dispatcher, storage) -> None:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    await on_startup()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    from app.scheduler.jobs import setup_scheduler

    setup_scheduler(scheduler, bot=bot, storage=storage, session_factory=session_factory)
    scheduler.start()

    await bot.set_webhook(
        url=f"{settings.webhook_host}{settings.webhook_path}",
        secret_token=settings.webhook_secret_token or None,
        drop_pending_updates=True,
    )
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.webhook_secret_token or None,
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)
    log.info("bot webhook mulai di %s%s", settings.webapp_host, settings.webapp_port)
    web.run_app(app, host=settings.webapp_host, port=settings.webapp_port)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN belum diisi — salin .env.example ke .env lalu isi.")

    storage = build_storage()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher(storage)

    if settings.bot_mode == "webhook":
        asyncio.run(run_webhook(bot, dp, storage))
    else:
        asyncio.run(run_polling(bot, dp, storage))


if __name__ == "__main__":
    main()
