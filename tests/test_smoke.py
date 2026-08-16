"""Smoke test: aplikasi bisa di-assemble (dispatcher, router, middleware)."""

from aiogram.fsm.storage.memory import MemoryStorage

from app.handlers import register_all_routers
from main import build_storage


class TestAssembly:
    def test_build_dispatcher(self, app_dispatcher):
        dp, storage = app_dispatcher
        assert dp is not None
        assert isinstance(storage, MemoryStorage)
        assert "session_factory" in dp.workflow_data
        # 13 router: common, transactions, wallets, transfer, categories, budgets,
        # summary, insight, upgrade, export, settings, admin, quick_add
        assert len(dp.sub_routers) == 13

    def test_register_all_routers(self):
        assert callable(register_all_routers)

    def test_storage_fallback_memory(self, app_dispatcher):
        _, storage = app_dispatcher
        assert isinstance(storage, MemoryStorage)
        assert isinstance(build_storage(), MemoryStorage)
