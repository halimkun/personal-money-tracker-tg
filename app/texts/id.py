"""Teks statis Bahasa Indonesia."""

WELCOME_NEW = (
    "👋 Halo! Selamat datang di <b>MoneyBot</b> — asisten pencatatan keuangan pribadimu.\n\n"
    "Langkah pertama: buat wallet pertamamu. Wallet itu 'dompet' tempat uangmu — "
    "misalnya <b>Cash</b>, <b>BCA</b>, atau <b>GoPay</b>."
)

WELCOME_WALLET_DONE = (
    "🎉 Wallet pertama berhasil dibuat!\n\n"
    "Sekarang kamu bisa langsung catat transaksi. Caranya:\n\n"
    "💬 <b>Ketik bebas</b> — contoh: <i>beli kopi 25rb</i>, <i>gaji masuk 5jt ke BCA</i>\n"
    "📷 <b>Kirim foto struk</b> — bot akan menganalisisnya\n"
    "✍️ Atau pakai <b>/catat</b> untuk input manual terstruktur\n\n"
    "Lihat semua perintah: /help"
)

WELCOME_BACK = "👋 Halo lagi, {name}! Ketik /help untuk daftar perintah."

HELP_TEXT = """📖 <b>Daftar Perintah</b>

💬 <b>Quick-add</b> — cukup ketik bebas atau kirim foto struk:
• <i>beli kopi 25rb</i>
• <i>gaji bulan ini masuk 5jt ke BCA</i>
• <i>transfer 500rb dari cash ke gopay</i>
• 📷 <i>kirim foto struk minimarket</i>

<b>Command:</b>
/catat — catat transaksi manual (step-by-step)
/riwayat — lihat & edit/hapus transaksi
/ringkasan — laporan harian/mingguan/bulanan
/wallet — kelola wallet & lihat saldo
/transfer — transfer antar wallet
/budget — atur budget per kategori/total
/kategori — kelola kategori custom
/insight — insight keuangan dari AI
/status — status akun & saldo
/upgrade — upgrade ke premium
/pengaturan — setting personal (insight AI, wallet default)
/export — export riwayat ke CSV
/cancel — batalkan proses yang sedang berjalan
"""

MSG_AI_LIMIT = (
    "⚠️ Kamu sudah mencapai batas harian analisis AI (quick-add). "
    "Silakan coba lagi besok, atau gunakan /catat untuk input manual."
)

MSG_AI_FAIL = (
    "⚠️ Gagal menganalisis pesanmu (layanan AI error). "
    "Coba lagi nanti, atau pakai /catat untuk input manual."
)

MSG_AI_UNCLEAR = (
    "😊 Hmm, pesanmu sepertinya bukan transaksi. "
    "Kalau mau mencatat transaksi, tulis seperti <i>beli kopi 25rb</i> "
    "atau pakai /catat untuk input manual."
)

MSG_FREEMIUM_BLOCKED = (
    "🚫 Kuota transaksi gratis bulanan kamu sudah habis.\n\n"
    "Untuk tetap mencatat tanpa batas, upgrade ke premium: /upgrade"
)

UPGRADE_CANCEL_HELP = "Ketik /cancel untuk membatalkan proses ini."
