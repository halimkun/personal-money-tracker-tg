# 💰 MoneyBot — Bot Telegram Pencatatan Keuangan Pribadi

Bot Telegram multi-user untuk mencatat pemasukan/pengeluaran dengan **AI quick-add** (teks bebas & foto), multi-wallet, transfer antar wallet, budget dengan alert, AI insight bulanan, dan monetisasi freemium. Dibangun sesuai `PRD_Bot_Keuangan_Telegram.md` — Python 3.12, `uv`, aiogram 3.x, SQLAlchemy 2.0 async, PostgreSQL 16 (dev: SQLite), Alembic, APScheduler.

## ✨ Fitur

| Fase PRD | Fitur | Command |
|---|---|---|
| MVP Inti | Registrasi + setup wallet awal (tanya nama di /start) | `/start` |
| | CRUD wallet (tambah, rename, default ⭐, nonaktifkan) | `/wallet` |
| | Catat transaksi manual (tipe → jumlah → wallet → kategori → catatan → konfirmasi) | `/catat` |
| | Riwayat transaksi + pagination + filter (tipe/wallet/kategori) | `/riwayat` |
| | Edit & hapus transaksi (edit memakai callback token, PRD §7c) | ✏️ / 🗑 di riwayat |
| | Transfer antar wallet (tabel terpisah, saldo divalidasi) | `/transfer` |
| | Kategori kustom + kata kunci untuk AI | `/kategori` |
| | Ringkasan harian/mingguan/bulanan + delta vs periode sebelumnya | `/ringkasan` |
| Admin & Monetisasi | Panel admin (statistik, daftar user, grant premium, broadcast) | `/admin` |
| | Opsi A: pembayaran manual → kirim bukti foto → approval admin (token `ap:`) | `/upgrade` |
| | Freemium: batas transaksi gratis/bulan, counter bulanan, premium seumur hidup | otomatis |
| Budget | Budget total/per kategori, mingguan/bulanan, threshold alert 80% | `/budget` |
| | Alert **hanya saat crossing** (tidak spam), prioritas "terlampaui" > "peringatan" | otomatis |
| AI Insight | Insight bulanan on-demand + riwayat | `/insight` |
| | Insight otomatis via scheduler (bisa dimatikan user/global) | APScheduler |
| AI Quick-Add | Ketik bebas: `beli kopi 25rb` / foto struk → kartu konfirmasi wajib | ketik / kirim foto |
| | Deteksi transfer antar wallet, koreksi kategori/wallet/jumlah/catatan di kartu | tombol kartu |
| | Rate limit harian per user, counter pemakaian AI per bulan | otomatis |
| Hardening | State locking (PRD §7b), callback ≤64 byte (PRD §7c) | middleware |
| | Polling & webhook (PRD §12), Redis FSM untuk produksi | `.env` |
| | Audit: source AI + file_id foto, log admin, token sekali-pakai | otomatis |

## 🏗️ Arsitektur (Layered)

Alur request mengikuti lapisan satu arah — **handler tidak pernah menyentuh database langsung**:

```
┌─────────────────────────────────────────────────────────────┐
│  handlers/   Presentasi — aiogram FSM, keyboard, pesan       │
│  middlewares/ DbSession → Registration → Locking (PRD §7b)   │
├─────────────────────────────────────────────────────────────┤
│  services/   Orkestrasi bisnis — validasi, alur, kalkulasi   │
│              memanggil repositori & domain                   │
├─────────────────────────────────────────────────────────────┤
│  repositories/  Akses data — satu-satunya lapisan yang       │
│                 memakai SQLAlchemy session                   │
├─────────────────────────────────────────────────────────────┤
│  domain/     Logika murni — uang, periode, alert, freemium   │
│              TANPA dependensi (pure function, mudah di-test) │
└─────────────────────────────────────────────────────────────┘
   Infrastruktur pendukung:
   ai/ (klien OpenAI-compatible, parser quick-add, insight, rate limiter)
   scheduler/ (APScheduler: insight bulanan, reset counter, expiry draft)
   db/ (models, base) · utils/ (format, enkripsi, pesan) · texts/id
```

**Struktur direktori:**

```
app/
├── ai/            # client.py (OpenAI-compatible), parser.py, insights.py, tracker.py
├── db/            # models.py (SQLAlchemy 2.0), base.py
├── domain/        # money.py, periods.py, logic.py, enums.py  ← murni, tanpa dependensi
├── handlers/      # 13 router: common, transactions, wallets, transfer, categories,
│                  #   budgets, summary, insight, upgrade, export, settings, admin,
│                  #   quick_add (registrasi PALING akhir)
├── keyboards/     # builder inline keyboard (callback pendek)
├── middlewares/   # db_session.py, registration.py, locking.py (state-locking PRD §7b)
├── repositories/  # base.py + 1 repo per entitas
├── scheduler/     # jobs.py — 5 job APScheduler
├── services/      # orkestrasi bisnis + callback_refs.py (token PRD §7c)
├── texts/         # id.py — semua pesan user (Bahasa Indonesia)
├── utils/         # format.py, crypto.py, messages.py, pagination.py
├── config.py      # pydantic-settings (.env)
└── main.py (root) # build_storage/dispatcher, polling & webhook (PRD §12)
alembic/           # migrasi — 0001_initial.py (11 tabel)
tests/             # 50 test: domain, services, ai, smoke
```

## 🚀 Persiapan

Prasyarat: **Python ≥3.12** dan **[uv](https://docs.astral.sh/uv/)**.

```bash
uv sync --dev                 # install dependensi (asyncpg sudah termasuk)
cp .env.example .env          # lalu isi BOT_TOKEN & ADMIN_IDS minimal
```

`.env` wajib diisi:
- `BOT_TOKEN` — token dari @BotFather
- `ADMIN_IDS` — ID Telegram pemilik bot, dipisah koma (untuk `/admin`)

### Database

**Dev (tanpa Docker)** — default `sqlite+aiosqlite:///bot.db`, tidak perlu setup apa pun.
Migrasi: `uv run alembic upgrade head` (sekali, atau tiap ada versi baru).

**Produksi — full Docker (PostgreSQL 16 + Redis + bot)**: lihat bagian 🐳 Docker di bawah.

**Bot di host + DB dari compose** (dev dengan Postgres): uncomment `ports:` di
`docker-compose.yml`, jalankan `docker compose up -d postgres redis`, dan di `.env`:
`DATABASE_URL=postgresql+asyncpg://moneybot:moneybot@localhost:5432/moneybot`,
`REDIS_URL=redis://localhost:6379/0`.

### 🐳 Docker (full stack)

```bash
cp .env.example .env       # isi BOT_TOKEN & ADMIN_IDS minimal
docker compose up -d --build
docker compose logs -f bot
```

- `bot` — image dari `Dockerfile` (uv, cache layer), migrasi Alembic otomatis saat start
- `postgres:16-alpine` — data di volume `pgdata`
- `redis:7-alpine` — FSM storage (state bertahan saat restart), data di volume `redisdata`
- `DATABASE_URL`/`REDIS_URL` otomatis di-override menunjuk service di dalam compose
- Kredensial DB: `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` (default `moneybot`)
- Bot restart otomatis (`restart: unless-stopped`)

### Menjalankan bot

```bash
uv run python main.py        # polling (default, BOT_MODE=polling)
```

Mode webhook (PRD §12): isi `BOT_MODE=webhook`, `WEBHOOK_HOST`, `WEBHOOK_PATH`, `WEBHOOK_SECRET_TOKEN`, lalu jalankan seperti di atas (aiohttp mendengarkan di `WEBAPP_PORT`, default 8080).

## 🤖 Konfigurasi AI (quick-add & insight)

Setelah bot jalan, buka `/admin` → ⚙️ Set AI:
- API key & base URL — **OpenAI-compatible** (OpenAI, OpenRouter, Groq, self-hosted, dll)
- Model (default `gpt-4o-mini` — bisa diganti, termasuk model vision untuk foto struk)
- API key dienkripsi Fernet di DB (generate `ENCRYPTION_KEY`) dan bisa diganti **tanpa restart**

Pemakaian AI dilacak per bulan (`/admin` → Statistik) dan dibatasi per user per hari (`AI_DAILY_LIMIT`, default 30).

## ✅ Checklist Test End-to-End

Siapkan 2 akun Telegram: **User** + **Admin** (ID di `ADMIN_IDS`).

**1. Onboarding & wallet**
- [ ] `/start` → bot menanya nama → tanya tipe wallet → minta saldo awal → selesai
- [ ] `/start` kedua kali (kembali setelah selesai) → langsung view ringkasan + tombol 🏠 Menu, tidak setup ulang

**2. Transaksi manual**
- [ ] `/catat` → pilih Pemasukan → jumlah `25.500` (dan coba format `25k`, `25 rb`, salah: `abc`) → pilih wallet → kategori → catatan (Lewati juga dicoba) → kartu konfirmasi → Simpan
- [ ] Salah ketik → tombol ❌ Batal mengedit pesan kartu jadi "Dibatalkan"
- [ ] `/riwayat` menampilkan baris dengan ikon kategori & saldo bertambah

**3. Transfer**
- [ ] Buat wallet kedua dulu (`/wallet` → Tambah)
- [ ] `/transfer` → dari → ke → jumlah melebihi saldo → error ditolak rapi
- [ ] Transfer valid tersimpan; saldo kedua wallet berubah; `/riwayat` **tidak** menampilkan transfer (tabel terpisah)

**4. Kategori kustom**
- [ ] `/kategori` → Tambah → tipe Pengeluaran → nama `Ngopi` → kata kunci `kopi, starbucks, janji jiwa`
- [ ] Hapus kategori bawaan → ditolak (hanya kustom yang bisa dihapus)

**5. Quick-add AI (setelah admin set API key)**
- [ ] Ketik `beli kopi 25rb di starbucks` → kartu konfirmasi muncul dengan kategori **Ngopi** (dari kata kunci)
- [ ] Tekan ✏️ Ubah Kategori / Jumlah / Catatan → koreksi → kembali ke kartu
- [ ] ✅ Simpan → tersimpan dengan `source=ai_text`
- [ ] Ketik `transfer 50 ribu ke BCA` → kartu transfer antar wallet
- [ ] Ketik `besok ada acara` → balasan "tidak jelas" (PRD §5.1b), tanpa memanggil FSM lain
- [ ] Kirim foto struk → kartu transaksi (butuh model vision)
- [ ] Diamkan 15 menit tanpa menyimpan → kartu otomatis "kadaluarsa"

**6. Ringkasan**
- [ ] `/ringkasan` → tombol Hari/Minggu/Bulan berpindah tanpa pesan baru (edit message), ada delta 📈/📉 vs periode sebelumnya

**7. Budget & alert**
- [ ] `/budget` → Tambah → kategori `Ngopi` → Rp 100.000 → Bulanan
- [ ] Catat pengeluaran hingga **melewati 80%** → pesan alert masuk sekali
- [ ] Lanjut hingga **melewati 100%** → alert "terlampaui"
- [ ] Catat lagi (masih di atas 100%) → **tidak** ada spam alert
- [ ] Toggle ⏸/▶️ dan hapus budget berjalan

**8. Freemium (opsional)**
- [ ] Admin: `/admin` → Pengaturan → toggle `payment_required` + set `free_transaction_limit` (mis. 5)
- [ ] User baru mencapai 5 transaksi → transaksi ke-6 ditolak dengan pesan upgrade
- [ ] Transfer **tidak** dihitung ke batas gratis

**9. Upgrade premium (Opsi A manual)**
- [ ] User: `/upgrade` → Bayar → kirim foto bukti
- [ ] Admin: menerima pesan bukti + 2 tombol (✅/❌) — token `ap:` dibuat **per admin** yang menekan
- [ ] Admin setujui → User jadi premium, batas transaksi hilang; `/upgrade` menampilkan status premium

**10. Admin & insight**
- [ ] `/admin` → Statistik, Daftar User (pagination), Pending Payments, Broadcast
- [ ] Broadcast: tulis teks → preview → kirim (hanya user aktif)
- [ ] `/admin` → Grant Premium untuk satu user
- [ ] `/insight` → Generate (butuh API key + transaksi bulan ini) → tampil + masuk Riwayat
- [ ] `/pengaturan` → matikan insight otomatis

**11. Hardening**
- [ ] Di tengah FSM `/catat`, ketik teks acak → tidak bocor ke quick-add AI (state locking)
- [ ] `/cancel` kapan pun mengeluarkan dari FSM dan menandai kartu "Dibatalkan"
- [ ] Tekan tombol lama/kedaluwarsa → "Tombol ini sudah tidak berlaku." (catch-all)

## 🧪 Test Otomatis

```bash
uv run pytest -q              # 50 test: domain murni, services, AI (mock), smoke
```

- `tests/test_domain.py` — parse/format uang, periode, logika budget-alert & freemium (tanpa DB)
- `tests/test_services.py` — orkestrasi bisnis end-to-end di SQLite in-memory
- `tests/test_ai.py` — parser & resolver quick-add dengan klien AI di-mock
- `tests/test_smoke.py` — dispatcher & storage terbangun benar (13 router, middleware, sesi)

## 📝 Catatan Penyesuaian dari PRD

1. **SQLite untuk dev/test** — PRD menyebut PostgreSQL 16; produksi tetap PostgreSQL via `DATABASE_URL` + `docker-compose.yml`. Tipe sengaja dibuat portabel (`BigInteger→Integer` variant untuk autoincrement SQLite).
2. **JSONB/TEXT[] → JSON** — `keywords` kategori disimpan sebagai JSON list agar satu skema jalan di kedua database. Migrasi Alembic sudah memakai tipe yang sama (diverifikasi `alembic revision --autogenerate` menghasilkan diff kosong).
3. **MemoryStorage fallback** — Redis dipakai bila `REDIS_URL` diisi (PRD §8); tanpa Redis, FSM memakai `MemoryStorage` (cukup untuk dev, state hilang saat restart — dikembalikan lewat `/cancel`).
4. **Monetisasi Opsi A saja** (pembayaran manual + approval admin) sesuai PRD §5.3; Midtrans/Opsi B tidak diimplementasikan.
5. **Datetime naive UTC** di DB; konversi zona waktu lokal (`TIMEZONE`, default Asia/Jakarta) di lapisan presentasi/domain.

## 🔒 Keamanan

- API key AI terenkripsi Fernet di database (`ENCRYPTION_KEY`)
- Callback token (`cb:`, `ap:`) terikat user_id, kadaluarsa 15 menit, sekali-pakai (PRD §7c)
- State locking middleware memblokir input di luar konten yang diizinkan per state FSM (PRD §7b)
- File foto struk disimpan sebagai `file_id` untuk audit, bukan diunduh ke server
