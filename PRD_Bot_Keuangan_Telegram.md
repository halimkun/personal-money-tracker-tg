# PRD — Bot Telegram Pencatatan Keuangan Pribadi

**Versi:** 0.1 (Draft)
**Tanggal:** 16 Agustus 2026
**Status:** Perencanaan awal

---

## 1. Ringkasan Proyek

Bot Telegram berbasis Python untuk mencatat transaksi keuangan pribadi, dipakai oleh diri sendiri dan orang-orang terdekat (multi-user). Data disimpan di PostgreSQL 16 (managed, Sumopod, 1GB). Bot punya sistem manajemen user, toggle fitur global/per-user, model freemium dengan batas transaksi gratis, dan insight bulanan otomatis dari AI (OpenAI-compatible).

### Tujuan
- Pencatatan transaksi cepat via chat, tanpa perlu buka aplikasi terpisah — termasuk input bahasa natural yang diklasifikasi otomatis oleh AI
- Manajemen multi-wallet (cash, bank, e-wallet, dst) termasuk transfer antar wallet
- Manajemen budget per kategori/wallet dengan alert
- Model monetisasi opsional (bisa dimatikan sepenuhnya jika hanya ingin dipakai gratis oleh circle terdekat)
- Insight otomatis bulanan berbasis AI untuk membantu user memahami pola pengeluaran

---

## 2. Tech Stack

| Komponen | Pilihan | Alasan |
|---|---|---|
| Bahasa | Python 3.12+ | Sesuai permintaan |
| Bot framework | **aiogram 3.x** | Async native, punya FSM (Finite State Machine) bawaan untuk multi-step conversation — cocok dengan requirement state management kamu |
| Database | PostgreSQL 16 (Sumopod, 1GB) | Sudah diputuskan |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | Standar industri, mendukung migration & relasi kompleks |
| Migration | Alembic | Versioning schema DB |
| Scheduler | APScheduler (AsyncIOScheduler) | Untuk job bulanan (insight AI) dan cron lain (reset free tier, reminder, dst) |
| AI Client | `openai` Python SDK (arahkan `base_url` custom) | Mendukung OpenAI asli maupun endpoint OpenAI-compatible lain (OpenRouter, Groq, self-hosted LLM, dst) sesuai requirement kamu |
| Hosting bot | VPS/Container Sumopod (opsional, satu provider dgn DB) | Latency rendah ke DB, billing dalam Rupiah, tidak perlu server sendiri |
| Environment/secret | `.env` untuk bootstrap (bot token, admin id awal, DB URL) | Kredensial sensitif lain (AI key) disimpan di DB terenkripsi, bisa diubah runtime tanpa redeploy |
| Testing | pytest + pytest-asyncio + testcontainers (Postgres) | Test terisolasi dengan DB sungguhan di container |

**Catatan penting soal hosting bot:** Managed DB Sumopod itu tempat data, tapi *proses bot Python-nya* tetap butuh tempat jalan 24/7 (baik pakai polling atau webhook). Karena kamu bilang tidak punya server sendiri, kamu tetap butuh compute — bisa VPS/container kecil di Sumopod juga (mereka jual keduanya), atau alternatif seperti Railway/Fly.io. Menempatkan bot & DB di provider yang sama akan mengurangi latency dan mempermudah manajemen.

---

## 3. Arsitektur Sistem (High Level)

```
Telegram User
     │
     ▼
Telegram Bot API (webhook/polling)
     │
     ▼
┌─────────────────────────────┐
│   Bot Application (aiogram) │
│  - Handlers (command/callback)
│  - FSM (multi-step input)
│  - Middleware (auth, rate limit, feature flag check)
└──────────────┬───────────────┘
               │
      ┌────────┴────────┐
      ▼                 ▼
┌───────────┐    ┌──────────────┐
│ PostgreSQL │    │  AI Provider  │
│ (Sumopod)  │    │ (OpenAI-compat)│
└───────────┘    └──────────────┘
      ▲
      │
┌─────┴──────┐
│ APScheduler │  → job bulanan: generate insight, reset counter, dst
└────────────┘
```

---

## 4. Skema Database (Draft)

### `users`
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | BIGINT PK | internal id |
| telegram_id | BIGINT UNIQUE | id user Telegram |
| username | TEXT | opsional |
| full_name | TEXT | |
| is_active | BOOLEAN | banned/tidak |
| is_premium | BOOLEAN | status bayar |
| premium_until | TIMESTAMP | null = lifetime/unlimited (kalau manual grant) |
| free_transaction_count | INT | counter transaksi gratis yang sudah dipakai |
| ai_insight_enabled | BOOLEAN | toggle per-user untuk insight AI |
| created_at | TIMESTAMP | |

### `wallets`
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | BIGINT PK | |
| user_id | FK → users.id | |
| name | TEXT | mis. "BCA", "Cash", "GoPay" |
| type | ENUM('cash','bank','ewallet','other') | untuk icon/grouping otomatis |
| initial_balance | NUMERIC(14,2) | saldo awal saat wallet dibuat |
| is_default | BOOLEAN | wallet default kalau AI/parsing tidak menyebut wallet spesifik |
| is_active | BOOLEAN | soft-delete |
| created_at | TIMESTAMP | |

> **Catatan desain:** saldo wallet (`current_balance`) **tidak disimpan sebagai kolom statis**, tapi dihitung on-the-fly: `initial_balance + Σincome − Σexpense − Σtransfer_out + Σtransfer_in`. Ini menghindari bug klasik "saldo tidak sinkron" kalau ada edit/hapus transaksi lama. Kalau nanti data sudah besar dan query agregasi mulai lambat, baru pertimbangkan materialized balance yang di-update via trigger/job — tapi untuk skala data kamu (lihat estimasi §Storage), ini bukan concern jangka pendek.

### `transactions` (khusus income & expense — bukan transfer)
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | BIGINT PK | |
| user_id | FK → users.id | |
| wallet_id | FK → wallets.id | wallet mana yang kena dampak |
| type | ENUM('income','expense') | |
| amount | NUMERIC(14,2) | |
| category_id | FK → categories.id | |
| note | TEXT | opsional |
| source | ENUM('manual','ai_text','ai_image') | untuk tracking asal pencatatan: FSM manual, AI dari teks bebas, atau AI dari analisis foto |
| source_file_id | TEXT, nullable | `file_id` foto Telegram (bukan gambar itu sendiri) — hanya diisi kalau `source='ai_image'`, untuk audit/debug |
| occurred_at | DATE | tanggal transaksi (bisa beda dari created_at) |
| created_at | TIMESTAMP | |

### `wallet_transfers` (tabel terpisah dari transactions)
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | BIGINT PK | |
| user_id | FK | |
| from_wallet_id | FK → wallets.id | |
| to_wallet_id | FK → wallets.id | |
| amount | NUMERIC(14,2) | jumlah yang dipindahkan |
| fee | NUMERIC(14,2) | opsional, biaya admin transfer (mis. antar bank) |
| note | TEXT | opsional |
| occurred_at | DATE | |
| created_at | TIMESTAMP | |

> **Kenapa transfer dipisah dari `transactions`?** Transfer itu net-zero terhadap total kekayaan user (uang cuma pindah tempat, bukan masuk/keluar beneran). Kalau digabung ke tabel `transactions` dengan trik "expense di wallet A + income di wallet B", laporan pemasukan/pengeluaran bulanan jadi bias (keliatan seperti user belanja padahal cuma mindahin saldo). Memisahkan tabel membuat laporan income/expense tetap akurat, dan laporan "riwayat lengkap" tinggal gabungkan (UNION) dua tabel ini saat query.

### `budgets`
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | BIGINT PK | |
| user_id | FK | |
| category_id | FK, nullable | null = budget total (semua kategori), diisi = budget spesifik kategori |
| wallet_id | FK, nullable | opsional, kalau mau budget spesifik per wallet |
| period_type | ENUM('weekly','monthly') | |
| amount | NUMERIC(14,2) | batas budget |
| alert_threshold_pct | INT | default 80, kapan mulai warning (mis. di 80% pemakaian) |
| is_active | BOOLEAN | |
| created_at | TIMESTAMP | |

### `categories`
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | BIGINT PK | |
| user_id | FK, nullable | null = default/global category |
| name | TEXT | |
| type | ENUM('income','expense') | |
| icon | TEXT | emoji, opsional |
| keywords | TEXT[] | opsional — daftar kata kunci untuk bantu AI mengklasifikasi teks bebas ke kategori ini lebih akurat (mis. kategori "Makan" ⇒ keywords: kopi, makan, warteg, gofood) |

### `global_settings` (key-value, cuma diakses admin)
| key | contoh value | keterangan |
|---|---|---|
| `payment_required` | `false` | master switch monetisasi |
| `free_transaction_limit` | `200` | batas gratis sebelum diminta bayar |
| `ai_insight_enabled_global` | `true` | master switch fitur AI insight |
| `ai_api_key` | (terenkripsi) | |
| `ai_base_url` | `https://api.openai.com/v1` | |
| `ai_model` | `gpt-4o-mini` | |

### `payments` (riwayat pembayaran/upgrade)
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | PK | |
| user_id | FK | |
| amount | NUMERIC | |
| status | ENUM('pending','approved','rejected') | |
| method | TEXT | manual transfer/QRIS/dll |
| proof_file_id | TEXT | file_id foto bukti transfer di Telegram |
| approved_by | FK admin, nullable | |
| created_at, approved_at | TIMESTAMP | |

### `ai_insights` (histori insight yang sudah digenerate)
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | PK | |
| user_id | FK | |
| period | TEXT | misal "2026-08" |
| content | TEXT | hasil insight dari AI |
| created_at | TIMESTAMP | |

### `admin_logs` (audit trail perubahan settingan)
| Kolom | Tipe | Keterangan |
|---|---|---|
| id | PK | |
| admin_id | FK | |
| action | TEXT | misal "update ai_model" |
| detail | JSONB | |
| created_at | TIMESTAMP | |

### `callback_refs` (alias pendek untuk callback_data yang kompleks — lihat §7c)
| Kolom | Tipe | Keterangan |
|---|---|---|
| token | VARCHAR(12) PK | string acak pendek (base62) |
| user_id | FK → users.id | validasi kepemilikan saat dipakai |
| purpose | TEXT | jenis aksi terkait |
| payload | JSONB | data lengkap untuk eksekusi aksi |
| created_at | TIMESTAMP | |
| expires_at | TIMESTAMP | default +15 menit |
| used_at | TIMESTAMP, nullable | untuk aksi sekali-pakai (mis. approve pembayaran) |

---

## 5. Daftar Fitur

### 5.1 Fitur User (semua user)

| Fitur | Prioritas | Pola UX |
|---|---|---|
| `/start` — onboarding, cek/registrasi user baru, buat wallet default pertama | Wajib | Multi-step (minta nama wallet pertama, mis. "Cash") |
| Tambah transaksi manual (income/expense) | Wajib | **Multi-step (FSM)**: pilih tipe → jumlah → wallet → kategori → catatan (opsional) → konfirmasi |
| **Quick-add via teks bebas (AI-parsed)** | Fitur andalan | AI parsing → **kartu konfirmasi wajib** (edit message), lihat §5.1b |
| Lihat transaksi terakhir (list + pagination, filter per wallet/kategori) | Wajib | Edit message (tombol Next/Prev/Filter) |
| Edit/hapus transaksi | Wajib | Multi-step (pilih transaksi → konfirmasi aksi) |
| Ringkasan harian/mingguan/bulanan (bisa per wallet) | Wajib | Edit message (tombol ganti periode/wallet) |
| **Kelola wallet** (tambah, edit nama, nonaktifkan, lihat saldo per wallet) | Wajib | List = edit message; tambah wallet = multi-step |
| **Transfer antar wallet** (manual `/transfer` atau via AI quick-add) | Wajib | Multi-step: wallet asal → wallet tujuan → jumlah → catatan → konfirmasi |
| **Kelola budget** (set/lihat/edit budget per kategori atau total) | Wajib | List = edit message; set budget = multi-step |
| **Notifikasi budget alert** (otomatis saat mendekati/lewat batas) | Wajib | Push message otomatis (dicek tiap transaksi baru masuk) |
| Kelola kategori custom (tambah/hapus, termasuk keywords bantu AI) | Nice-to-have | Multi-step |
| Insight bulanan AI (otomatis + on-demand `/insight`) | Fitur andalan | Push message otomatis (scheduler) + command manual |
| Export data (CSV, termasuk riwayat transfer) | Nice-to-have | Single action → kirim file |
| Setting notifikasi (mis. reminder harian catat transaksi) | Nice-to-have | Edit message (toggle) |
| Cek status akun (`/status`) — sisa kuota gratis, status premium, ringkasan saldo semua wallet | Wajib | Single message |
| `/upgrade` — alur upgrade ke premium | Wajib (jika payment_required aktif) | Multi-step |

### 5.1b Quick-Add via AI (Teks Bebas & Gambar) — Fitur Utama Baru

Ini mengubah cara utama user mencatat transaksi. Alih-alih selalu lewat command `/catat` + FSM step-by-step, user bisa langsung kirim **teks bebas atau foto** (mis. struk belanja) ke bot, misalnya:

> "beli kopi 25rb"
> "gaji bulan ini masuk 5jt ke BCA"
> "transfer 500rb dari cash ke gopay"
> *(kirim foto struk minimarket)*

**Alur teknis:**

1. **Deteksi pesan** — global middleware memeriksa dulu **status lock user** (lihat §7 — State Locking Policy). Kalau user sedang punya proses aktif yang menunggu feedback, pesan/foto baru langsung ditolak dengan alasan + opsi, **tidak diteruskan ke AI** (hemat biaya panggilan AI yang sia-sia). Kalau user free (tidak locked) dan pesan bukan command → lanjut ke langkah 2.
2. **AI parsing** — kirim ke AI:
   - Kalau teks: teks user + daftar kategori & wallet milik user (sebagai context)
   - Kalau foto: gambar (perlu model AI yang mendukung vision/image input, bukan sekadar model teks) + daftar kategori & wallet milik user
   
   Minta output terstruktur (JSON):
   ```json
   {
     "action": "transaction | transfer | unclear",
     "type": "income | expense",
     "amount": 25000,
     "category_guess": "Makan & Minum",
     "wallet_guess": "Cash",
     "note": "beli kopi (Indomaret)",
     "confidence": "high | low"
   }
   ```
3. **Cek `action: unclear`** — kalau AI menilai pesan/gambar bukan transaksi (user cuma chat biasa, atau foto tidak jelas/bukan struk) atau confidence rendah → bot tidak memaksakan, cukup balas singkat mempersilakan pakai `/catat` manual. Tidak ada state yang terbuka (tidak mengunci apa pun), karena tidak ada draft yang perlu diputuskan user.
4. **Set state `QuickAddStates.awaiting_confirmation`** — begitu hasil parsing valid, bot **menyimpan state FSM eksplisit** (bukan sekadar data tanpa state seperti draft awal) berisi payload hasil parsing di FSM context data. Inilah yang jadi dasar mekanisme locking: selama state ini aktif, user dianggap "sedang punya draft yang belum diputuskan".
5. **Kartu konfirmasi (WAJIB)** — hasil parsing ditampilkan sebagai satu pesan dengan inline keyboard, pola **edit message**:
   ```
   📝 Konfirmasi Transaksi (dari: 📷 foto / 💬 teks)
   Tipe: Pengeluaran
   Jumlah: Rp 25.000
   Kategori: Makan & Minum
   Wallet: Cash
   Catatan: beli kopi (Indomaret)

   [✅ Simpan]  [✏️ Ubah Kategori]  [✏️ Ubah Wallet]  [❌ Batal]
   ```
   - Tombol `✅ Simpan` → commit ke DB (`transactions.source`: `'ai_text'` atau `'ai_image'` tergantung sumber input), **clear state** → user kembali ke kondisi unlocked
   - Tombol `✏️ Ubah Kategori` / `Ubah Wallet` → tampilkan daftar pilihan (edit message, tetap dalam state yang sama — bukan state baru, cukup update FSM data)
   - Kalau user perlu koreksi jumlah/catatan (free text) → transisi ke `QuickAddCorrectionStates` (masih terhitung "locked", tetap 1 rangkaian proses yang sama)
   - `❌ Batal` → buang data pending, **clear state** → user kembali unlocked, tidak ada yang tersimpan
6. **Auto-expire** — kalau draft tidak diputuskan dalam waktu tertentu (mis. 15 menit), scheduler job membersihkan state tsb otomatis (clear FSM state + edit kartu jadi "⌛ Draft kadaluarsa, kirim ulang kalau masih ingin dicatat") supaya user tidak terjebak lock selamanya kalau lupa.

**Implikasi penting yang perlu kamu sadari:**

- **Biaya bertambah signifikan**, dan **input gambar lebih mahal dari teks** (model vision umumnya charge token lebih besar per request dibanding teks biasa). Untuk 30 user aktif yang rutin kirim foto struk, biaya AI bisa jadi komponen terbesar — pantau lewat `/stats`.
- **Selalu sediakan fallback manual.** Kalau AI API down/error/timeout (termasuk kalau model yang di-set admin ternyata tidak mendukung vision padahal user kirim foto), bot harus tetap bisa jalan lewat `/catat` FSM manual biasa tanpa AI sama sekali, dan beri pesan error yang jelas ke user ("gagal menganalisis, coba `/catat` manual atau kirim ulang").
- **Rate limiting per user** perlu ditambahkan supaya tidak ada user yang spam teks/foto dan menghabiskan kuota/biaya AI.
- **Validasi model vision di admin panel** — saat admin set `ai_model`, sebaiknya ada catatan/pengecekan apakah model tsb mendukung image input, supaya tidak baru ketahuan gagal saat user pertama kali kirim foto.
- Field `transactions.source_file_id` (opsional) bisa dipakai menyimpan `file_id` foto dari Telegram (bukan menyimpan gambar itu sendiri, cukup reference id-nya) — berguna untuk audit/debug kalau hasil parsing AI ternyata salah dan kamu ingin cek ulang struk aslinya. Ini ringan karena cuma string, tidak menambah beban storage berarti.

### 5.2 Fitur Admin (hanya kamu / admin ID terdaftar)

| Fitur | Keterangan |
|---|---|
| Dashboard admin (`/admin`) | Menu utama, semua toggle di sini pakai **inline keyboard + edit message** |
| Toggle `payment_required` global | Edit message, tombol ON/OFF langsung |
| Set `free_transaction_limit` | Multi-step (minta input angka) |
| Toggle AI insight global | Edit message |
| Set AI: `api_key`, `base_url`, `model` | Multi-step per field (karena butuh input teks) |
| Manajemen user: list, cari, ban/unban, grant premium manual | List = edit message w/ pagination; grant/ban = konfirmasi multi-step |
| Approve/reject pembayaran manual | Edit message dengan tombol Approve/Reject di setiap notifikasi bukti bayar masuk |
| Broadcast pesan ke semua user | Multi-step (ketik pesan → preview → konfirmasi kirim) |
| Lihat statistik global (jumlah user, transaksi, estimasi ukuran DB) | Single message, auto-generate |

### 5.3 Sistem Monetisasi (Freemium)

Alur logika:
1. Setiap kali user coba tambah transaksi → cek `payment_required` (global) & `is_premium` (user)
2. Kalau `payment_required = false` → semua fitur terbuka, tidak ada batas
3. Kalau `payment_required = true` DAN user belum premium:
   - Cek `free_transaction_count` vs `free_transaction_limit`
   - Kalau masih di bawah limit → izinkan, counter naik
   - Kalau sudah melebihi → tolak, tampilkan pesan upgrade + tombol `/upgrade`
4. User premium (`is_premium = true`) → bebas limit, tidak peduli `payment_required`

**Soal metode pembayaran** — ini perlu kamu putuskan karena mempengaruhi kompleksitas:
- **Opsi A (paling sederhana, cocok untuk MVP/circle kecil):** User transfer manual (QRIS/rekening pribadi kamu) → upload bukti transfer sebagai foto ke bot → masuk ke antrian approval admin → kamu approve manual dari dashboard admin
- **Opsi B (otomatis, lebih effort):** Integrasi payment gateway lokal seperti **Midtrans** atau **Xendit** → generate QRIS otomatis → webhook konfirmasi otomatis set `is_premium = true`

Rekomendasi saya: **mulai dari Opsi A**. Untuk skala pengguna circle terdekat, approval manual sama sekali tidak merepotkan, dan menghindari kompleksitas integrasi payment gateway + biaya admin fee mereka di awal. Bisa upgrade ke Opsi B nanti kalau user bertambah banyak.

### 5.4 Sistem AI Monthly Insight

- Berjalan otomatis via scheduler (misal tanggal 1 tiap bulan, generate insight bulan sebelumnya)
- Hanya jalan untuk user yang: `ai_insight_enabled_global = true` DAN `user.ai_insight_enabled = true`
- Isi insight: ringkasan pemasukan/pengeluaran, kategori terbesar, perbandingan dengan bulan sebelumnya, saran singkat (semua digenerate lewat prompt ke AI berdasarkan data agregat transaksi user — **bukan** mengirim seluruh raw data user ke AI demi efisiensi & privasi, cukup kirim angka agregat yang sudah diproses)
- Disimpan di tabel `ai_insights` supaya user bisa lihat ulang histori insight lewat command, tidak hilang setelah dikirim

### 5.5 Fitur Tambahan yang Saya Sarankan (opsional, bisa masuk roadmap fase 2+)

| Fitur | Manfaat |
|---|---|
| **Recurring transaction** | Catat otomatis transaksi rutin (misal langganan bulanan) tanpa input manual tiap bulan |
| **Reminder harian** | "Belum catat transaksi hari ini nih" kalau user biasanya rajin tapi lupa |
| **Shared/family group budget** | Beberapa user gabung dalam 1 "grup" untuk lihat pengeluaran bersama (misal budget rumah tangga) |
| **Referral/invite bonus** | User yang invite teman dapat tambahan kuota gratis — bagus untuk growth organik di circle kamu |

---

## 6. Daftar Command Bot (Lengkap)

### Command User

| Command | Fungsi |
|---|---|
| `/start` | Onboarding, registrasi, buat wallet pertama |
| `/help` atau `/bantuan` | Daftar command & cara pakai (termasuk contoh format quick-add) |
| `/catat` | Tambah transaksi manual via FSM terstruktur (fallback dari quick-add AI) |
| *(teks bebas, tanpa command)* | Quick-add via AI parsing — lihat §5.1b |
| `/riwayat` | Lihat daftar transaksi (list + pagination + filter) |
| `/ringkasan` | Laporan harian/mingguan/bulanan |
| `/wallet` | Kelola wallet: lihat daftar, tambah, edit, set default, lihat saldo |
| `/transfer` | Transfer antar wallet secara manual/terstruktur |
| `/kategori` | Kelola kategori custom |
| `/budget` | Lihat/atur budget per kategori atau total |
| `/insight` | Minta insight AI on-demand (di luar jadwal otomatis bulanan) |
| `/status` | Status akun: kuota gratis tersisa, status premium, ringkasan saldo semua wallet |
| `/upgrade` | Mulai alur upgrade ke premium |
| `/pengaturan` | Setting personal: toggle insight AI, toggle reminder, wallet default |
| `/export` | Export riwayat transaksi ke CSV |
| `/cancel` | Batalkan FSM/alur yang sedang berjalan (safety net kapan pun user "nyangkut") |

### Command Admin (hanya admin ID terdaftar)

| Command | Fungsi |
|---|---|
| `/admin` | Buka dashboard admin (menu utama, semua toggle di sini) |
| `/broadcast` | Kirim pesan ke semua/sebagian user |
| `/stats` | Statistik global: jumlah user, transaksi, estimasi ukuran DB, estimasi biaya AI bulan berjalan |
| `/grantpremium` | Shortcut cepat grant premium ke user tertentu tanpa lewat approval pembayaran |
| `/setai` | Shortcut ke setting AI (api key, base url, model) — juga bisa lewat `/admin` |

> **Catatan:** `/cancel` penting untuk selalu tersedia sebagai *global command* yang bisa memotong FSM state apa pun — ini standar UX bot dengan banyak alur multi-step supaya user tidak pernah benar-benar "terjebak".

---

## 7. Desain State Management (FSM)

Gunakan `aiogram.fsm` dengan state group terpisah per alur. Contoh:

```python
class AddTransactionStates(StatesGroup):
    choosing_type = State()
    entering_amount = State()
    choosing_wallet = State()
    choosing_category = State()
    entering_note = State()
    confirming = State()

class QuickAddStates(StatesGroup):
    # state ini yang jadi dasar mekanisme locking untuk AI quick-add
    # (lihat §7b) — selama state ini aktif, user dianggap "locked"
    awaiting_confirmation = State()

class QuickAddCorrectionStates(StatesGroup):
    # dipakai HANYA saat user perlu koreksi field free-text
    # dari hasil parsing AI (mis. jumlah salah baca). Pemilihan
    # kategori/wallet tetap lewat edit message, bukan state ini.
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

class AdminSetAIStates(StatesGroup):
    entering_api_key = State()
    entering_base_url = State()
    entering_model = State()

class UpgradeStates(StatesGroup):
    waiting_proof_photo = State()
```

**Aturan pembagian pola UX (sesuai requestmu):**
- **Edit message (callback_query + `edit_message_text`/`edit_message_reply_markup`)** → dipakai untuk semua toggle ON/OFF, navigasi list/pagination, pilih dari daftar terbatas (kategori, periode laporan). Tidak butuh state tersimpan karena semua informasi ada di `callback_data`.
- **FSM multi-step (`Message` + `state.set_state()`)** → dipakai saat butuh free-text input dari user: jumlah transaksi, catatan, API key, nama kategori custom, dll. Selalu sediakan tombol "Batal" di tiap step supaya user tidak nyangkut di state.
- Tambahkan **middleware** global untuk auto-clear state kalau user kirim command baru di tengah FSM (`/start`, `/cancel`) — mencegah state "nyangkut" jadi bug umum di bot berbasis FSM.

---

## 7b. Kebijakan State Locking & Pending Action

Ini formalisasi dari requirement kamu: **selama ada state aktif yang menunggu feedback user, aksi baru yang tidak relevan harus ditolak — bukan diproses diam-diam atau malah menimpa state sebelumnya.**

### Definisi "locked"
User dianggap **locked** kalau `FSMContext.get_state()` mengembalikan state apa pun yang **bukan `None`**. Ini otomatis mencakup dua kategori yang tadinya kamu pikir terpisah, tapi sengaja disatukan supaya cukup 1 mekanisme pengecekan:

1. **FSM multi-step biasa** — sedang di tengah `/catat`, `/wallet` tambah baru, `/transfer`, `/budget`, setting admin, dll.
2. **Pending AI quick-add** — sudah kirim teks/foto, AI sudah analisis, tapi kartu konfirmasi belum ditekan Simpan/Batal (state `QuickAddStates.awaiting_confirmation`). Ini yang jadi contoh kasusmu: user kirim foto struk kedua sebelum approve/reject yang pertama.

Kalau **tidak locked** (`state is None`) → user bebas mulai command/quick-add baru kapan saja, tidak ada restriksi.

### Yang terjadi kalau locked dan user melakukan aksi baru
Global middleware (jalan sebelum semua handler lain, kecuali beberapa exception di bawah) mengecek lock, dan kalau kena:

- **Pesan baru langsung ditolak**, tidak diproses (tidak diteruskan ke AI, tidak masuk DB — sesuai tujuanmu menghemat pemanggilan AI & data yang sia-sia)
- Bot balas dengan **alasan spesifik + opsi jelas**, contoh untuk kasus kirim foto struk kedua saat yang pertama belum di-approve:
  ```
  ⚠️ Kamu masih punya transaksi hasil analisis foto sebelumnya
  yang menunggu konfirmasi (Simpan/Batal).

  Pilihan kamu:
  1️⃣ Scroll ke atas, tekan tombol Simpan/Batal di kartu tersebut
  2️⃣ Ketik /cancel untuk membatalkan proses itu, baru kirim yang baru
  ```
  Pesan penolakan ini idealnya **kontekstual sesuai state aktifnya** (pesan beda untuk "lagi isi form wallet" vs "lagi nunggu approve quick-add") — ambil dari mapping state → pesan, bukan pesan generik.

### Command yang dikecualikan dari lock (selalu boleh diproses)
- `/cancel` — wajib selalu bisa memutus lock, ini satu-satunya jalan keluar
- `/help`, `/status` — command murni informasional/read-only, aman diizinkan tanpa mengganggu state aktif (tidak menyentuh data apa pun)

Semua command lain (termasuk kirim teks/foto bebas, `/catat`, `/wallet`, dst) **diblokir** selama locked.

### Efek `/cancel`
- Clear FSM state ke `None`
- Buang seluruh draft/data pending terkait (kartu konfirmasi quick-add yang masih terbuka di-edit jadi "❌ Dibatalkan oleh user")
- Tidak ada apa pun yang tersimpan ke DB dari proses yang dibatalkan

---

## 7c. Desain Callback Data (Batas 64 Byte Telegram)

Telegram membatasi `callback_data` pada inline button **maksimal 64 byte** — ini batas keras dari platform, bukan sesuatu yang bisa dinegosiasikan. Kalau kita coba menumpuk banyak informasi langsung di situ (misal: aksi + id transaksi + id kategori + id wallet sekaligus), gampang kebentur limit ini begitu datanya makin kompleks. Solusinya seperti yang kamu maksud: **jangan simpan detail di callback_data, cukup simpan referensi pendek yang nunjuk ke data lengkap di database.**

### Dua tingkatan strategi (tidak semua callback butuh alias — hanya yang berisiko besar)

**Tingkat 1 — Encoding langsung (untuk kasus sederhana & aman)**
Dipakai kalau datanya memang cuma 1-2 nilai kecil (angka ID, enum pendek). Contoh:
```
page:next
menu:wallet
toggle:payment_required:on
cat:15
qa:confirm
qa:setcat:15
```
Ini semua jelas jauh di bawah 64 byte, tidak perlu alias — over-engineering kalau semua callback dipaksa lewat DB lookup.

**Tingkat 2 — Token/alias ke database (untuk kasus kompleks/berisiko)**
Dipakai kalau butuh menyertakan banyak parameter sekaligus, ID yang besar, atau payload terstruktur (mis. hasil parsing AI, aksi admin dengan beberapa opsi). Tabel baru:

### `callback_refs`
| Kolom | Tipe | Keterangan |
|---|---|---|
| token | VARCHAR(12) PK | string acak pendek (base62), unik |
| user_id | FK → users.id | **wajib divalidasi** saat dipakai — cegah user A memicu callback milik user B |
| purpose | TEXT | jenis aksi, mis. `'admin_payment_decision'`, `'edit_transaction'` |
| payload | JSONB | data lengkap yang dibutuhkan untuk eksekusi aksi |
| created_at | TIMESTAMP | |
| expires_at | TIMESTAMP | default +15 menit (bisa beda per `purpose`) |
| used_at | TIMESTAMP, nullable | ditandai setelah dipakai — untuk aksi sensitif (approve pembayaran, dst) token **sekali pakai**, mencegah tombol lama ditekan ulang (replay) |

Format `callback_data` dengan token: `"cb:{token}"` — misal `"cb:aZ3kP9dQ1x"`, total ~14 byte, jauh di bawah limit 64 byte berapa pun kompleksnya payload aslinya di database.

**Alur pakai:**
1. Saat generate kartu dengan tombol kompleks (mis. approval pembayaran admin: butuh `payment_id` + `admin_id` + opsi approve/reject) → insert row baru ke `callback_refs`, dapat `token`
2. Tombol pakai `callback_data="cb:<token>"`
3. Saat ditekan → handler lookup `callback_refs` by token → **validasi `user_id` cocok** dengan user yang menekan tombol (proteksi keamanan) dan belum `expires_at`/`used_at` → eksekusi aksi sesuai `purpose` + `payload` → tandai `used_at` kalau aksinya sensitif/final

**Housekeeping:** tambahkan job terjadwal (APScheduler) untuk hapus row `callback_refs` yang sudah `expires_at` lewat atau sudah `used_at` — supaya tabel ini tidak menumpuk sia-sia (relevan mengingat kita cuma punya kuota 1GB total di database).

---

## 8. Testing Plan

| Level | Cakupan | Tools |
|---|---|---|
| Unit test | Business logic murni (kalkulasi limit, validasi input, format currency) | pytest |
| Integration test | Query DB, transaksi rollback, migration | pytest-asyncio + testcontainers (Postgres 16 di Docker, terpisah dari DB production) |
| Handler test | Simulasi update Telegram (mock `Message`/`CallbackQuery`) tanpa perlu bot asli online | aiogram test utils / manual mock |
| AI integration test | Mock response OpenAI-compatible API (jangan panggil API asli tiap test run — boros kuota & biaya) | `responses`/`httpx` mock |
| Manual E2E test | Checklist skenario nyata di bot staging (token Telegram terpisah dari production) | Checklist manual (lihat di bawah) |

### Checklist Manual E2E (contoh, sebelum go-live)
- [ ] User baru `/start` → berhasil registrasi
- [ ] Tambah transaksi lengkap (semua field FSM jalan, termasuk tombol batal)
- [ ] Lihat ringkasan bulanan, angka sesuai
- [ ] Free tier: transaksi ke-201 (dgn limit 200) → ditolak & muncul CTA upgrade
- [ ] Toggle `payment_required` ke OFF dari admin → user tanpa premium bisa transaksi tanpa batas
- [ ] Upload bukti bayar → masuk antrian admin → admin approve → `is_premium` otomatis true
- [ ] Insight AI jalan otomatis di tanggal terjadwal (test dengan mempercepat cron di staging)
- [ ] User matikan `ai_insight_enabled` personal → tidak menerima insight meski global ON
- [ ] Ganti `ai_base_url`/`model` dari admin panel → insight berikutnya pakai config baru
- [ ] Restart bot proses → state FSM yang sedang berjalan tidak bikin crash (idealnya FSM storage persisten, bukan in-memory — lihat catatan teknis di bawah)
- [ ] Buat 2 wallet, transfer antar wallet → saldo kedua wallet ter-update benar, transaksi TIDAK muncul di laporan income/expense
- [ ] Set budget kategori "Makan" → transaksi yang membuat pemakaian lewat `alert_threshold_pct` → user dapat notifikasi otomatis
- [ ] Quick-add: kirim teks "beli kopi 25rb" → muncul kartu konfirmasi dengan data benar → tekan Simpan → transaksi masuk dgn `source='ai_parsed'`
- [ ] Quick-add: kirim teks ambigu/bukan transaksi (mis. "halo bot") → AI tidak memaksakan pencatatan, bot balas wajar
- [ ] Quick-add: tekan "Ubah Kategori" di kartu konfirmasi → daftar kategori muncul, pilih baru → kartu ter-update, data lain tidak berubah
- [ ] Simulasikan AI API down/timeout → `/catat` manual tetap berfungsi normal (fallback tidak boleh gagal)
- [ ] **Locking:** kirim foto struk → sebelum approve/reject, kirim foto struk kedua → ditolak dengan pesan alasan + opsi, foto kedua TIDAK dikirim ke AI (cek log/biaya tidak nambah)
- [ ] **Locking:** saat locked, ketik `/cancel` → state clear, kartu draft ter-update jadi "Dibatalkan", user bisa mulai quick-add baru
- [ ] **Locking:** saat locked, coba `/status` atau `/help` → tetap berhasil diproses (command exception)
- [ ] **Quick-add gambar:** kirim foto struk asli → hasil parsing AI (amount/kategori) masuk akal dibanding isi struk
- [ ] **Callback token:** buat kartu approval admin dengan payload kompleks → token tersimpan di `callback_refs`, `callback_data` di bawah 64 byte → tekan tombol → aksi tereksekusi benar & row ditandai `used_at`
- [ ] **Callback token:** coba pakai token yang sudah `used_at` terisi (replay) → ditolak, tidak dieksekusi ulang
- [ ] **Callback token:** coba akses token dengan `user_id` yang beda dari pemilik asli → ditolak (proteksi lintas-user)
- [ ] Job cleanup `callback_refs` expired → row lama terhapus otomatis sesuai jadwal

**Catatan teknis penting:** Untuk FSM storage, jangan pakai `MemoryStorage` bawaan aiogram di production — kalau proses bot restart (deploy ulang, crash, dst), semua state user yang sedang di tengah alur akan hilang. Gunakan **Redis** sebagai FSM storage (aiogram punya `RedisStorage` built-in) supaya state bertahan meski bot restart. Ini juga murah — bisa pakai Redis kecil di provider yang sama.

---

## 9. Fase Development (Roadmap)

| Fase | Cakupan | Estimasi fokus |
|---|---|---|
| **Fase 0 — Setup** | Init project, DB schema + migration, koneksi bot dasar, deploy skeleton ke Sumopod | Fondasi |
| **Fase 1 — MVP Core** | CRUD transaksi manual, wallet, transfer antar wallet, kategori, ringkasan, user management dasar | Fitur inti harus jalan dulu (tanpa AI sama sekali) |
| **Fase 2 — Admin & Monetisasi** | Dashboard admin, toggle payment, free tier limit, alur upgrade manual | Bisnis logic |
| **Fase 3 — Budget** | Set budget, kalkulasi pemakaian, notifikasi alert | Melengkapi fitur inti sebelum AI masuk |
| **Fase 4 — AI Insight Bulanan** | Integrasi AI, scheduler bulanan, setting AI di admin panel | Fitur diferensiasi, risiko lebih rendah (frekuensi rendah, 1x/bulan/user) |
| **Fase 5 — AI Quick-Add** | Parsing teks bebas, kartu konfirmasi, fallback ke `/catat` | Paling kompleks & paling mahal biaya AI — sengaja ditaruh terakhir setelah semua fondasi (wallet, kategori, budget) stabil, karena quick-add butuh semua data itu sebagai context |
| **Fase 6 — Hardening & Testing** | Testing menyeluruh, FSM storage ke Redis, error handling, logging, rate limiting AI | Stabilitas sebelum dipakai orang lain |
| **Fase 7 — Nice-to-have** | Export CSV, recurring transaction, fitur tambahan dari daftar §5.5 | Setelah live & stabil |

> **Kenapa AI Quick-Add (Fase 5) ditaruh setelah AI Insight (Fase 4)?** Insight bulanan itu low-risk (jalan otomatis, jarang, gampang di-test terjadwal). Quick-add itu high-frequency, langsung menyentuh alur input data utama, dan biayanya paling besar — lebih aman dibangun setelah kamu sudah punya pengalaman nyata soal biaya & reliability AI provider dari fase insight terlebih dulu.

---

## 10. Hal yang Perlu Kamu Putuskan Sebelum Mulai Coding

1. **Hosting bot process** — pakai VPS/container Sumopod juga, atau provider lain (Railway/Fly.io)?
2. **Metode pembayaran** — mulai dari manual transfer + approval admin (rekomendasi saya), atau langsung integrasi payment gateway?
3. **AI provider default** — OpenAI langsung, atau provider lain yang lebih murah (OpenRouter, dst)? Ini makin penting karena quick-add AI dipanggil jauh lebih sering daripada insight bulanan.
4. **Redis untuk FSM storage** — perlu provisioning kecil tambahan (biasanya murah/gratis di tier kecil)
5. **Nama & branding bot** — untuk `/start` message, tone komunikasi ke user (formal/santai)
6. **Batas rate-limit quick-add AI per user** — misal maksimal berapa kali panggilan AI per user per hari, untuk kontrol biaya

---

## 11. Ringkasan Estimasi Biaya Bulanan (kasar)

| Komponen | Estimasi |
|---|---|
| PostgreSQL Sumopod 1GB | Rp 10.000/bulan (sudah kamu punya) |
| VPS/container untuk bot | ~Rp 15.000–60.000/bulan (tergantung spek) |
| Redis kecil (FSM storage) | Rp 0–15.000/bulan (tier kecil) |
| AI API — insight bulanan | 1x panggilan/user/bulan, murah — untuk puluhan user masih di bawah Rp 10.000/bulan dengan model murah |
| **AI API — quick-add (baru)** | Jauh lebih besar: kalau 30 user × 10 pesan/hari × 30 hari ≈ 9.000 panggilan/bulan. Dengan model murah (`gpt-4o-mini`/setara, prompt pendek), estimasi kasar **Rp 50.000–150.000/bulan** tergantung provider & panjang prompt. **Ini komponen biaya paling variabel — wajib dipantau di awal peluncuran fitur ini.** |
| **Total kasar** | **~Rp 75.000–235.000/bulan** tergantung pilihan & seberapa aktif fitur quick-add dipakai |

> Saran: aktifkan `/stats` admin untuk memantau jumlah panggilan AI real per bulan sejak Fase 5 mulai jalan, supaya bisa langsung ketahuan kalau biaya melonjak di luar estimasi — dan bisa cepat pasang rate-limit lebih ketat kalau perlu.

---

## 12. Mode Menjalankan Bot: Polling vs Webhook

aiogram mendukung dua cara bot menerima update dari Telegram. Sebaiknya **kedua mode didukung dari awal** (dipilih lewat environment variable), bukan cuma salah satu, karena kebutuhan dev/testing dan production biasanya beda.

### Perbandingan

| | **Polling** | **Webhook** |
|---|---|---|
| Cara kerja | Bot aktif "nanya terus" ke server Telegram: "ada update baru?" (long polling) | Telegram yang aktif "kirim" update ke URL bot begitu ada event |
| Butuh domain/HTTPS publik? | **Tidak** — bisa jalan di laptop, di belakang NAT, tanpa domain sama sekali | **Ya, wajib** — Telegram cuma mau kirim ke URL HTTPS dengan sertifikat valid |
| Setup untuk testing lokal | Paling gampang — tinggal jalankan script, langsung nerima update | Butuh reverse tunnel (mis. `ngrok`/`cloudflared`) supaya localhost bisa diakses publik sementara |
| Cocok untuk | **Development & testing** (sesuai maksudmu), atau production skala kecil yang tidak butuh latency super rendah | Production — lebih efisien, latency lebih rendah, standar untuk bot yang sudah stabil |
| Resource | Koneksi terus-menerus ke Telegram (long-lived request) | Cuma aktif saat ada event masuk, lebih hemat idle |

### Desain implementasi

Gunakan environment variable `BOT_MODE` untuk switch, di-set di `.env`:

```env
# .env
BOT_MODE=polling          # atau: webhook

# Hanya dipakai kalau BOT_MODE=webhook
WEBHOOK_HOST=https://botkeuangan.namadomainkamu.com
WEBHOOK_PATH=/webhook/telegram
WEBHOOK_SECRET_TOKEN=<random-string-rahasia>
WEBAPP_HOST=0.0.0.0
WEBAPP_PORT=8080
```

Struktur entrypoint (`main.py`) bercabang berdasarkan `BOT_MODE`:

```python
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=RedisStorage.from_url(REDIS_URL))
    # ... register semua router/handler ...

    if settings.BOT_MODE == "polling":
        await bot.delete_webhook(drop_pending_updates=True)  # pastikan webhook lama nonaktif
        await dp.start_polling(bot)

    elif settings.BOT_MODE == "webhook":
        await bot.set_webhook(
            url=f"{settings.WEBHOOK_HOST}{settings.WEBHOOK_PATH}",
            secret_token=settings.WEBHOOK_SECRET_TOKEN,
        )
        app = web.Application()
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=settings.WEBHOOK_SECRET_TOKEN,
        ).register(app, path=settings.WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        await web._run_app(app, host=settings.WEBAPP_HOST, port=settings.WEBAPP_PORT)
```

**Poin keamanan penting untuk webhook:** selalu set `secret_token` dan validasi header `X-Telegram-Bot-Api-Secret-Token` di tiap request masuk. Tanpa ini, siapa pun yang tahu URL webhook-mu bisa kirim payload palsu yang bot proses seolah-olah dari Telegram asli.

### Rekomendasi alur kerja

- **Development & testing sehari-hari → `BOT_MODE=polling`.** Sesuai instingmu, ini paling praktis: tidak perlu domain, tidak perlu tunnel, tinggal jalankan dan langsung bisa dicoba dari HP.
- **Sebelum deploy ke production, opsional tes webhook dulu** pakai `ngrok`/`cloudflared` untuk memastikan alur webhook (termasuk validasi secret token) benar-benar jalan, tanpa harus langsung pasang di server production.
- **Production di Sumopod** — karena Sumopod (sesuai riset saya sebelumnya) juga menyediakan domain siap pakai untuk aplikasi yang di-deploy, ini cocok dipakai untuk webhook kalau kamu memang ingin pindah ke mode ini nanti. Tapi **polling di production juga tetap valid pilihan** untuk skala circle terdekat — bedanya cuma soal efisiensi resource & latency, bukan soal fitur yang hilang. Tidak perlu buru-buru pindah ke webhook kalau polling sudah terasa cukup responsif.
- Tambahkan ke checklist testing (§8): pastikan `bot.delete_webhook()` selalu dipanggil sebelum start polling (mencegah error "conflict" kalau webhook lama masih ke-set di sisi Telegram), dan sebaliknya pastikan tidak ada proses polling lain yang jalan bersamaan saat pindah ke mode webhook.

---

*Dokumen ini adalah draft awal — struktur tabel, nama field, dan detail teknis lain bisa disesuaikan lagi saat masuk ke tahap implementasi.*
