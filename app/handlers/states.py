"""State group FSM per alur (PRD §7)."""

from aiogram.fsm.state import State, StatesGroup


class AddTransactionStates(StatesGroup):
    choosing_type = State()
    entering_amount = State()
    choosing_wallet = State()
    choosing_category = State()
    entering_note = State()
    confirming = State()


class EditTransactionStates(StatesGroup):
    choosing_amount = State()
    choosing_category = State()
    entering_note = State()
    confirming = State()


class QuickAddStates(StatesGroup):
    # state ini yang jadi dasar mekanisme locking untuk AI quick-add (PRD §7b)
    awaiting_confirmation = State()


class QuickAddCorrectionStates(StatesGroup):
    # dipakai HANYA untuk koreksi field free-text (jumlah/catatan) dari hasil AI
    correcting_amount = State()
    correcting_note = State()


class WalletStates(StatesGroup):
    entering_name = State()
    choosing_type = State()
    entering_initial_balance = State()


class TransferStates(StatesGroup):
    choosing_from_wallet = State()
    choosing_to_wallet = State()
    entering_amount = State()
    entering_note = State()
    confirming = State()


class BudgetStates(StatesGroup):
    choosing_scope = State()      # total atau per kategori
    choosing_category = State()   # skip kalau scope = total
    entering_amount = State()
    choosing_period = State()


class CategoryStates(StatesGroup):
    entering_name = State()
    choosing_type = State()
    entering_keywords = State()


class AdminInputStates(StatesGroup):
    entering_free_limit = State()
    entering_price = State()
    entering_api_key = State()
    entering_base_url = State()
    entering_model = State()
    entering_daily_limit = State()
    entering_instructions = State()


class BroadcastStates(StatesGroup):
    entering_text = State()


class UpgradeStates(StatesGroup):
    waiting_proof_photo = State()
