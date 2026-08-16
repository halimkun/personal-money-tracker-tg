"""Helper render pesan Telegram (PRD §7).

Dua metode merespon user:

1. TRANSAKSIONAL (butuh input user: teks, foto, atau pilihan wizard) →
   multi-step dengan pesan baru tiap langkah:
   - `render_step` mengirim prompt langkah sebagai pesan baru dan menyimpan
     `msg_id` + `msg_text` di FSM data. User selalu melihat riwayat
     jawabannya di chat; prompt tidak pernah menimpa pesan sebelumnya.
   - `confirm_step` meng-edit pesan prompt langkah SEBELUMNYA untuk
     menempelkan pilihan/input user di situ ("Anda memilih: X" / teks yang
     diketik), lalu tombolnya dihilangkan. Update pesan dalam alur
     transaksional DIPAKAI HANYA untuk konfirmasi ini.

2. INFO & TOGGLE (lihat settingan/daftar, ganti on-off, navigasi menu) →
   `edit_or_send` update pesan di tempat. Setelah alur transaksional selesai,
   panel/menu asal di-refresh di tempat lewat `edit_or_send` juga
   (simpan message_id-nya di FSM data saat alur dimulai).

Alur contoh /catat:
  1. bot kirim pesan baru "📝 Mau catat apa?" + tombol
  2. user tekan "💸 Pengeluaran" → pesan 1 di-edit jadi
     "📝 Mau catat apa?\\n———\\nAnda memilih: 💸 Pengeluaran"
  3. bot kirim pesan baru "💸 Masukkan jumlah pengeluaran…"
  4. user ketik "25000" → pesan 3 di-edit jadi "…\\n———\\n💵 Rp 25.000"
     dst.
"""

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

async def edit_or_send(bot, chat_id: int, message_id: int | None, text: str,
                       kb: InlineKeyboardMarkup | None = None) -> int:
    """Edit message kalau masih bisa, kalau gagal kirim baru. Return message_id baru."""
    if message_id:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id,
                reply_markup=kb, parse_mode=ParseMode.HTML,
            )
            return message_id
        except TelegramBadRequest:
            pass
    sent = await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return sent.message_id


async def render_step(bot, chat_id: int, state, text: str,
                      kb: InlineKeyboardMarkup | None = None, *,
                      edit: bool = False) -> int:
    """Render prompt langkah FSM.

    Default: kirim sebagai pesan BARU (multi-step — tiap prompt adalah pesan
    baru). `edit=True` hanya untuk re-render langkah yang SAMA (mis. pagination
    daftar kategori), bukan transisi antar langkah.

    Menyimpan `msg_id` + `msg_text` di FSM data — dipakai `confirm_step`.
    """
    if edit:
        data = await state.get_data()
        msg_id = await edit_or_send(bot, chat_id, data.get("msg_id"), text, kb)
    else:
        sent = await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        msg_id = sent.message_id
    await state.update_data(msg_id=msg_id, msg_text=text)
    return msg_id


async def confirm_step(bot, chat_id: int, state, suffix: str) -> None:
    """Konfirmasi pilihan/input user: tempel `suffix` di prompt langkah sebelumnya.

    Prompt di-edit dari `msg_text` menjadi `msg_text\\n———\\nsuffix` dan
    tombolnya dihilangkan (tidak bisa ditekan dua kali). Gagal edit (mis.
    pesan terhapus) diabaikan.
    """
    data = await state.get_data()
    msg_id, text = data.get("msg_id"), data.get("msg_text", "")
    if not msg_id or not text:
        return
    try:
        await bot.edit_message_text(
            f"{text}\n———\n{suffix}",
            chat_id=chat_id, message_id=msg_id,
            reply_markup=None, parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest:
        pass
