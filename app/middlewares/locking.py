"""State Locking Policy (PRD §7b).

Selama user punya state FSM aktif yang menunggu feedback, pesan/command baru
ditolak dengan alasan kontekstual — KECUALI:
- input yang memang ditunggu state tersebut (mis. teks jumlah saat entering_amount)
- command /cancel (satu-satunya jalan keluar), /help, /status (read-only)

Callback query TIDAK diblokir di sini — tiap handler callback memvalidasi
datanya sendiri (kepemilikan/kedaluwarsa token), sehingga tombol kartu aktif
tetap berfungsi. Ini juga memastikan pesan/foto baru TIDAK diteruskan ke AI
saat user locked (hemat biaya — PRD §5.1b poin 1).
"""

from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from aiogram.types.update import UpdateTypeLookupError

from app.handlers.states import (
    AddTransactionStates,
    AdminInputStates,
    BroadcastStates,
    BudgetStates,
    CategoryStates,
    EditTransactionStates,
    QuickAddCorrectionStates,
    QuickAddStates,
    TransferStates,
    UpgradeStates,
    WalletStates,
)

# Command yang SELALU boleh diproses meski user locked (PRD §7b)
EXEMPT_COMMANDS = {"/cancel", "/help", "/bantuan", "/status"}

# State yang memang menunggu input pesan — jenis konten yang diterima
TEXT_INPUT_STATES: dict[str, set[str]] = {
    AddTransactionStates.entering_amount.state: {"text"},
    AddTransactionStates.entering_note.state: {"text"},
    EditTransactionStates.choosing_amount.state: {"text"},
    EditTransactionStates.entering_note.state: {"text"},
    QuickAddCorrectionStates.correcting_amount.state: {"text"},
    QuickAddCorrectionStates.correcting_note.state: {"text"},
    WalletStates.entering_name.state: {"text"},
    WalletStates.entering_initial_balance.state: {"text"},
    TransferStates.entering_amount.state: {"text"},
    TransferStates.entering_note.state: {"text"},
    BudgetStates.entering_amount.state: {"text"},
    CategoryStates.entering_name.state: {"text"},
    CategoryStates.entering_keywords.state: {"text"},
    AdminInputStates.entering_free_limit.state: {"text"},
    AdminInputStates.entering_price.state: {"text"},
    AdminInputStates.entering_api_key.state: {"text"},
    AdminInputStates.entering_base_url.state: {"text"},
    AdminInputStates.entering_model.state: {"text"},
    AdminInputStates.entering_daily_limit.state: {"text"},
    AdminInputStates.entering_instructions.state: {"text"},
    BroadcastStates.entering_text.state: {"text"},
    UpgradeStates.waiting_proof_photo.state: {"photo"},
}

MSG_LOCKED_QUICKADD = (
    "⚠️ Kamu masih punya transaksi hasil analisis sebelumnya yang menunggu "
    "konfirmasi (Simpan/Batal).\n\n"
    "Pilihan kamu:\n"
    "1️⃣ Scroll ke atas, tekan tombol Simpan/Batal di kartu tersebut\n"
    "2️⃣ Ketik /cancel untuk membatalkan proses itu, baru kirim yang baru"
)

MSG_LOCKED_CATAT = (
    "⚠️ Kamu sedang di tengah proses catat transaksi. Selesaikan dulu "
    "lewat tombol yang tersedia, atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_WALLET = (
    "⚠️ Kamu sedang di tengah pengaturan wallet. Selesaikan dulu "
    "lewat tombol yang tersedia, atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_TRANSFER = (
    "⚠️ Kamu sedang di tengah proses transfer. Selesaikan dulu "
    "lewat tombol yang tersedia, atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_BUDGET = (
    "⚠️ Kamu sedang di tengah pengaturan budget. Selesaikan dulu "
    "lewat tombol yang tersedia, atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_CATEGORY = (
    "⚠️ Kamu sedang di tengah pengaturan kategori. Selesaikan dulu "
    "lewat tombol yang tersedia, atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_ADMIN = (
    "⚠️ Ada proses admin yang sedang berjalan. Selesaikan dulu "
    "atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_UPGRADE = (
    "⚠️ Kamu sedang di alur upgrade premium. Kirim foto bukti transfer, "
    "atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_EDIT = (
    "⚠️ Kamu sedang mengedit transaksi. Selesaikan dulu lewat tombol yang "
    "tersedia, atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_BROADCAST = (
    "⚠️ Kamu sedang menyusun broadcast. Kirim teks pesannya, "
    "atau ketik /cancel untuk membatalkan."
)

MSG_LOCKED_GENERIC = (
    "⚠️ Ada proses yang sedang berjalan. Selesaikan dulu, "
    "atau ketik /cancel untuk membatalkan."
)


def _lock_message_for(state: str) -> str:
    if state == QuickAddStates.awaiting_confirmation.state:
        return MSG_LOCKED_QUICKADD
    if state.startswith("AddTransactionStates:"):
        return MSG_LOCKED_CATAT
    if state.startswith("EditTransactionStates:"):
        return MSG_LOCKED_EDIT
    if state.startswith("QuickAddCorrectionStates:"):
        return MSG_LOCKED_QUICKADD
    if state.startswith("WalletStates:"):
        return MSG_LOCKED_WALLET
    if state.startswith("TransferStates:"):
        return MSG_LOCKED_TRANSFER
    if state.startswith("BudgetStates:"):
        return MSG_LOCKED_BUDGET
    if state.startswith("CategoryStates:"):
        return MSG_LOCKED_CATEGORY
    if state.startswith("AdminInputStates:"):
        return MSG_LOCKED_ADMIN
    if state.startswith("BroadcastStates:"):
        return MSG_LOCKED_BROADCAST
    if state.startswith("UpgradeStates:"):
        return MSG_LOCKED_UPGRADE
    return MSG_LOCKED_GENERIC


class LockingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Middleware dp.update menerima objek Update mentah — ambil event aslinya
        if not isinstance(event, Update):
            return await handler(event, data)
        try:
            inner = event.event
        except UpdateTypeLookupError:
            return await handler(event, data)
        if not isinstance(inner, Message):
            # callback dll divalidasi oleh handler masing-masing
            return await handler(event, data)
        state = data.get("state")
        if state is None:
            return await handler(event, data)
        current = await state.get_state()
        if current is None:
            return await handler(event, data)

        text = (inner.text or inner.caption or "").strip()
        if text.startswith("/"):
            command = text.split()[0].split("@")[0].lower()
            if command in EXEMPT_COMMANDS:
                return await handler(event, data)
            await inner.answer(_lock_message_for(current))
            return None

        content_type = "photo" if inner.photo else ("text" if inner.text else "other")
        allowed = TEXT_INPUT_STATES.get(current, set())
        if content_type in allowed:
            return await handler(event, data)

        await inner.answer(_lock_message_for(current))
        return None
