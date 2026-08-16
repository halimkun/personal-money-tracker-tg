"""Fixture bersama: SQLite in-memory (satu koneksi static-pool) untuk semua test."""

from datetime import date, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db import models  # noqa: F401


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(scope="session")
def app_dispatcher():
    """Dispatcher aplikasi — dibangun SEKALI per sesi test.

    Router aiogram tidak bisa di-attach dua kali, jadi semua test dispatch
    berbagi instance ini. Test menyuntikkan session_factory (DB in-memory)
    miliknya sendiri lewat `dp["session_factory"]`.
    """
    from main import build_dispatcher, build_storage

    storage = build_storage()
    dp = build_dispatcher(storage)
    return dp, storage


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


async def make_user(session, *, is_premium: bool = False, tg_id: int = 111):
    from app.db.models import User

    user = User(
        telegram_id=tg_id,
        username="tester",
        full_name="Test User",
        is_premium=is_premium,
        created_at=datetime(2026, 8, 1),
    )
    session.add(user)
    await session.flush()
    return user


async def make_wallet(session, user_id: int, *, name: str = "Cash", initial: str = "0",
                      is_default: bool = True):
    from decimal import Decimal

    from app.db.models import Wallet

    w = Wallet(
        user_id=user_id, name=name, type="cash",
        initial_balance=Decimal(initial), is_default=is_default,
        created_at=datetime(2026, 8, 1),
    )
    session.add(w)
    await session.flush()
    return w


async def make_category(session, user_id: int | None, *, name: str = "Makan",
                        type_: str = "expense"):
    from app.db.models import Category

    c = Category(user_id=user_id, name=name, type=type_, icon="🍜", keywords=[])
    session.add(c)
    await session.flush()
    return c


async def make_tx(session, user_id: int, wallet_id: int, category_id: int, *,
                  type_: str = "expense", amount: str = "10000",
                  occurred_at: date | None = None):
    from decimal import Decimal

    from app.db.models import Transaction

    tx = Transaction(
        user_id=user_id, wallet_id=wallet_id, type=type_, amount=Decimal(amount),
        category_id=category_id, note=None, source="manual",
        occurred_at=occurred_at or date(2026, 8, 10),
        created_at=datetime(2026, 8, 10),
    )
    session.add(tx)
    await session.flush()
    return tx
