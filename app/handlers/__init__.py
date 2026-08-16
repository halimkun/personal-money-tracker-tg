"""Presentasi layer: router aiogram per fitur.

URUTAN registrasi penting: router dengan handler spesifik (FSM/command) harus
terdaftar SEBELUM quick_add (handler generik untuk teks bebas/foto), supaya
input FSM tidak tertangkap quick-add.
"""

from aiogram import Dispatcher


def register_all_routers(dp: Dispatcher) -> None:
    from app.handlers import (
        admin,
        budgets,
        categories,
        common,
        export,
        insight,
        quick_add,
        settings,
        summary,
        transactions,
        transfer,
        upgrade,
        wallets,
    )

    for module in (
        common,
        transactions,
        wallets,
        transfer,
        categories,
        budgets,
        summary,
        insight,
        upgrade,
        export,
        settings,
        admin,
        quick_add,  # handler generik — harus paling akhir
    ):
        dp.include_router(module.router)
