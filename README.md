# 🧾 Sales Canvas Bot — Telegram & WhatsApp

Bot yang menerima **laporan sales berupa foto struk**, membacanya otomatis (OCR),
menyimpan ke **database SQLite**, lalu menyediakan **analisa data** lewat:
perintah di bot (Telegram & WhatsApp) dan **dashboard web** (grafik).

```
foto struk ──▶ Telegram bot ──┐
foto struk ──▶ WhatsApp bot ──┼──▶ OCR (Tesseract) ──▶ Parser struk ──▶ SQLite
                              │                                        │
perintah laporan ◀────────────┘            dashboard web ◀─────────────┘
```

---

## ✨ Fitur

| Fitur | Keterangan |
|---|---|
| 📷 Terima foto struk | dari Telegram (foto) & WhatsApp (foto) |
| 🔍 OCR Bahasa Indonesia | Tesseract `ind+eng` + preprocessing OpenCV (binerisasi, deskew, upscale) |
| 🧾 Parser struk | ekstrak toko, tanggal, jam, item, subtotal, pajak, total, metode bayar |
| 🗄️ Database | SQLite (tabel `receipts` & `items`) |
| 📊 Dashboard web | penjualan harian, produk terlaris, metode bayar, penjualan per jam, struk terbaru |
| 🤖 Perintah laporan | `/laporan_harian`, `/laporan_mingguan`, `/laporan_bulanan`, `/produk_terlaris`, `/total` |
| 🔌 Tanpa sudo | Tesseract bisa disalin ke folder `vendor/` (sudah disertakan) |

---

## 🗂️ Struktur Project

```
├── run.py                      # jalankan server API + bot Telegram
├── app/
│   ├── config.py               # konfigurasi dari .env
│   ├── database.py             # SQLite (receipts, items)
│   ├── ocr.py                  # preprocessing OpenCV + Tesseract
│   ├── parser.py               # parse teks struk Indonesia
│   ├── analytics.py            # analisa data (pandas)
│   ├── process.py              # pipeline bersama kedua bot
│   ├── bots/
│   │   ├── telegram_bot.py     # bot Telegram
│   │   └── whatsapp_api.py     # webhook untuk bridge WhatsApp
│   └── web/
│       ├── server.py           # FastAPI: API analytics + dashboard
│       └── dashboard.html      # halaman dashboard (Chart.js)
├── whatsapp-bridge/            # bridge WhatsApp (Node.js + Baileys)
│   └── index.js
├── scripts/make_sample_receipt.py  # bikin struk contoh untuk uji coba
├── vendor/tesseract/           # Tesseract lokal (tanpa sudo)
└── data/                       # database + upload struk (dibuat otomatis)
```

---

## 🚀 Cara Menjalankan

### 0. Cara paling cepat: Docker

```bash
cp .env.example .env                          # isi TELEGRAM_BOT_TOKEN & BRIDGE_WEBHOOK_SECRET
cp whatsapp-bridge/.env.example whatsapp-bridge/.env

docker compose up -d --build

docker compose logs -f bridge                 # scan QR WhatsApp (sekali saja)
```

Buka dashboard: **http://IP-SERVER:8000/dashboard**

> Bot Telegram & API berjalan sebagai container `sales-bot-api`, bridge WhatsApp
> sebagai `sales-bot-whatsapp`. Data SQLite (folder `./data`) dan session WhatsApp
> (`./whatsapp-bridge/auth`) tersimpan di disk dan tetap ada walau container di-restart.
> Perlu **VPS/PC yang menyala 24 jam** agar bot selalu online.

### 1. Persiapan environment (tanpa Docker)

```bash
# Salin contoh konfigurasi
cp .env.example .env
cp whatsapp-bridge/.env.example whatsapp-bridge/.env

# Python
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Node (bridge WhatsApp)
cd whatsapp-bridge && npm install && cd ..
```

### 2. Tesseract (OCR)

Dua pilihan — project ini sudah menyertakan salinan di `vendor/tesseract/`,
jadi **biasanya tanpa install apa pun sudah jalan** (otomatis terdeteksi).

Alternatif resmi (perlu sudo sekali):
```bash
sudo apt install tesseract-ocr tesseract-ocr-ind
```

> Jika `vendor/` dihapus dan Tesseract sistem tidak ada, bot akan memberi
> peringatan saat menerima foto.

### 3. Token bot Telegram

1. Buka [@BotFather](https://t.me/BotFather) di Telegram → `/newbot`.
2. Salin token ke `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   BRIDGE_WEBHOOK_SECRET=buat-string-acak-panjang
   ```
3. (Opsional) Batasi pengguna: `TELEGRAM_ALLOWED_IDS=123456789`

### 4. Jalankan

```bash
# Terminal 1 — server API + dashboard + bot Telegram
.venv/bin/python run.py

# Terminal 2 — bridge WhatsApp (scan QR sekali di awal)
cd whatsapp-bridge && node index.js
```

Saat pertama kali bridge berjalan, **scan QR** yang muncul di terminal dengan
WhatsApp: *Pengaturan → Perangkat tertaut → Tautkan perangkat*.

### 5. Uji coba

Kirim foto struk ke bot Telegram, atau ke nomor WhatsApp Anda.
Tanpa struk asli? Buat struk contoh lalu kirim gambarnya:

```bash
.venv/bin/python scripts/make_sample_receipt.py
```

Buka dashboard: **http://localhost:8000/dashboard**

---

## 🤖 Perintah Bot

| Perintah | Fungsi |
|---|---|
| `/laporan_harian` | Penjualan hari ini + jam tersibuk |
| `/laporan_mingguan` | Rincian 7 hari terakhir |
| `/laporan_bulanan` | Pendapatan bulan ini, pertumbuhan vs bulan lalu, produk terlaris |
| `/produk_terlaris` | 10 produk terlaris (berdasarkan nilai penjualan) |
| `/total` | Ringkasan seluruh data |
| `/bantuan` | Daftar perintah |

Perintah yang sama bisa diketik langsung di chat WhatsApp.

---

## 📊 Dashboard Web

Berisi: total pendapatan, jumlah struk, penjualan hari ini, pertumbuhan bulanan,
grafik penjualan harian (7/30 hari), metode pembayaran (donut), produk terlaris
(bar), penjualan per jam, dan tabel struk terbaru. Auto-refresh tiap 60 detik.

---

## 🚢 Deploy ke VPS dengan Docker

1. **Siapkan VPS** (Ubuntu 22.04/24.04 disarankan) dengan Docker:
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   # logout-login agar grup docker aktif
   ```
2. **Clone repo:**
   ```bash
   git clone https://github.com/Faber-Aritonang/receipt-sales-bot.git
   cd receipt-sales-bot
   ```
3. **Konfigurasi:**
   ```bash
   cp .env.example .env
   cp whatsapp-bridge/.env.example whatsapp-bridge/.env
   nano .env    # isi TELEGRAM_BOT_TOKEN (dari @BotFather) & ganti BRIDGE_WEBHOOK_SECRET
   ```
4. **Jalankan:**
   ```bash
   docker compose up -d --build
   docker compose logs -f bridge   # scan QR WhatsApp, lalu Ctrl+C (container tetap jalan)
   docker compose ps
   ```
5. **Buka dashboard:** `http://IP-VPS:8000/dashboard`

> ⚠️ Buka port 8000 (dan 3100 jika perlu) di firewall VPS. Untuk HTTPS/domain,
> bisa gunakan Nginx reverse-proxy + Let's Encrypt, atau platform seperti
> Railway/Render (perlu sesuaikan — bridge butuh koneksi persisten).

---

## 🔧 Konfigurasi (.env)

| Variabel | Fungsi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token dari BotFather (kosong = bot Telegram nonaktif) |
| `TELEGRAM_ALLOWED_IDS` | ID pengguna yang boleh memakai bot (kosong = semua) |
| `BRIDGE_WEBHOOK_SECRET` | Rahasia bersama bridge Node ↔ server Python |
| `API_PORT` | Port dashboard (default 8000) |
| `OCR_LANG` | Bahasa OCR (default `ind+eng`) |
| `TESSERACT_CMD` / `TESSDATA_PREFIX` | Path tesseract (opsional, otomatis pakai vendor) |

---

## 🧪 Catatan Teknis

- **Akurasi OCR** bervariasi tergantung kualitas foto. Foto yang miring/kusam
  bisa membuat beberapa field kosong. Setiap struk diberi label akurasi
  (tinggi/sedang/rendah) di dashboard & balasan bot.
- Untuk akurasi jauh lebih tinggi (struk kusam/handphone miring), ganti modul
  OCR ke API vision (mis. OpenAI GPT-4o) — lihat `app/ocr.py`.
- Data tersimpan lokal di `data/sales.db` (SQLite). Backup cukup dengan
  menyalin folder `data/`.
- **Risiko nomor WhatsApp**: Baileys memakai koneksi tidak resmi. Hindari
  pesan massal/spam; untuk produksi komersial gunakan
  [WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api)
  (resmi Meta).

---

## 🐙 Repositori

Project ini open-source (MIT) di:
https://github.com/Faber-Aritonang/receipt-sales-bot
