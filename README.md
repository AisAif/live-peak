# 🚀 YouTube Live Highlight & Peak Data Analyzer

Proyek ini adalah **Data Analytics Pipeline** ringan berbasis **Python 3.10+ & FastAPI** yang memantau siaran langsung YouTube secara *real-time*, memproses volatilitas chat penonton (*chat velocity*), dan mendeteksi titik puncak momen menarik (*highlights/peaks*) menggunakan pendekatan statistik **Z-Score**.

---

## ✨ Fitur Utama

- 📡 **Passive Stream Discovery:** Mendeteksi siaran langsung YouTube aktif via RSS Feed / Passive HTTP Polling (bebas kuota Google API Key).
- 💬 **Real-Time Chat Ingestion:** Menyedot pesan chat secara asinkron (`pytchat`) dengan fitur *exponential backoff auto-reconnection*.
- 📈 **Sliding Window Analytics:** Agregasi statistik pesan per 10 detik dan deteksi lonjakan via **Z-Score algorithm**.
- 🔀 **Peak Merging & Time Padding:** Penggabungan puncak obrolan berdekatan ($\le 30$s) serta penambahan offset klip video ($-15$s s/d $+15$s).
- 🔤 **Emoji & Keyword Volatility:** Isolasi kata kunci dominan dan emoji yang memicu keramaian chat (dengan *stopwords* dinamis dari GitHub Raw).
- 📺 **24/7 Auto-Channel Tracker:** Monitoring kanal YouTube otomatis dari daftar channel/handle (`@PUBGMOBILE`) yang tersimpan di SQLite DB.
- 📊 **Interactive Live Dashboard:** Interface web visual bawaan di `/dashboard` (Chart.js via WebSockets).
- 🔐 **Protected Dashboard Auth:** Keamanan HTTP Basic Auth menggunakan kredensial username & password dari `.env`.
- 🔔 **Webhook Alert Notifications:** Notifikasi *real-time* ke Discord / Telegram saat *peak* terdeteksi.
- 💾 **Local Async SQLite Storage:** Penyimpanan data terstruktur permanen berbasis SQLAlchemy 2.0 Async + `aiosqlite`.

---

## 🛠️ Panduan Cara Setup & Menjalankan Proyek

### 1. Prasyarat Sistem
* **Python 3.10+** (Teruji kompatibel penuh di Python 3.10, 3.11, 3.12, 3.13, dan 3.14).
* **Git** (Opsional untuk *version control*).

---

### 2. Langkah Setup Proyek

#### Step A: Clone / Buka Repositori
Buka terminal (PowerShell / Command Prompt) di folder proyek:
```bash
cd C:\Users\Asus\Data\Projects\mY\live-peak
```

#### Step B: Buat & Aktivasi Virtual Environment (Opsional namun Disarankan)
```bash
# Membuat virtual environment .venv
python -m venv .venv

# Aktivasi di Windows PowerShell:
.\.venv\Scripts\activate

# Atau aktivasi di Command Prompt (cmd):
.\.venv\Scripts\activate.bat
```

#### Step C: Install Dependensi Python
```bash
pip install -r requirements.txt
```

#### Step D: Konfigurasi Environment Variable (`.env`)
Salin file `.env.example` menjadi `.env`:
```bash
cp .env.example .env
```
Isi atau sesuaikan variabel di file `.env`:
```env
# Dashboard Authentication Credentials
DASHBOARD_USERNAME="admin"
DASHBOARD_PASSWORD="admin123"

# Database Configuration (Async SQLite local DB)
DATABASE_URL="sqlite+aiosqlite:///./live_peak.db"

# Peak Detection & Analytics Parameters
Z_SCORE_THRESHOLD=2.5
WINDOW_DURATION_SECONDS=10
SLIDING_WINDOW_SIZE=30
PEAK_MERGE_GAP_SECONDS=30
PEAK_PADDING_BEFORE_SECONDS=15
PEAK_PADDING_AFTER_SECONDS=15
```

---

### 3. Menjalankan Server Aplikasi

Jalankan server menggunakan **Uvicorn**:
```bash
python -m uvicorn app.main:app --reload --port 8000
```

Setelah server menyala, Anda dapat meng-akses:
* 📊 **Interactive Live Dashboard:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)  
  *(Login menggunakan Username & Password dari `.env`)*
* 📖 **Swagger API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
* 💚 **Health Check API:** [http://localhost:8000/health](http://localhost:8000/health)

---

### 🧪 4. Menguji Sistem (Unit & Integration Tests)

Jalankan pengujian otomatis menggunakan `pytest`:
```bash
python -m pytest
```

---

## 🐳 Deploy di VPS via Docker Compose & Cloudflare Tunnel

Skema ini adalah cara **paling aman dan stabil** untuk menjalankan monitoring 24/7 tanpa perlu membuka port firewall (Zero Open Ports) dan menyembunyikan IP publik VPS Anda.

### 1. Buat Cloudflare Tunnel di Dashboard Cloudflare
1. Buka [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) > **Networks** > **Tunnels**.
2. Klik **Add a Tunnel** > Pilih **Cloudflared**.
3. Beri nama tunnel (misal `live-peak-vps`), lalu klik **Save tunnel**.
4. Di bagian *Install and run a connector*, pilih tab **Docker**.
5. Salin kode token panjang yang tertera setelah `--token` (misalnya: `eyJhIjoi...`).
6. Masuk ke tab **Public Hostname**:
   * **Subdomain**: misal `live` (atau domain utama Anda)
   * **Domain**: domain aktif Anda di Cloudflare
   * **Type**: `HTTP`
   * **URL**: `live-peak-app:8000` *(menggunakan nama container internal Docker)*
7. Klik **Save hostname**.

---

### 2. Setup di Server VPS
Clone repositori dan persiapkan file environment:
```bash
# Clone repository
git clone https://github.com/AisAif/live-peak.git
cd live-peak

# Salin template env
cp .env.example .env
```

Edit file `.env` di VPS (`nano .env`):
```env
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=password_rahasia_anda
DATABASE_URL=sqlite+aiosqlite:///./data/live_peak.db
TUNNEL_TOKEN=eyJhIjoi...token_cloudflare_anda...
```

---

### 3. Jalankan Kontainer via Docker Compose
```bash
# Build dan jalankan di background
docker compose up -d --build

# Cek status kontainer
docker compose ps

# Cek log aplikasi & tunnel
docker compose logs -f
```

Data SQLite akan tersimpan secara otomatis dan persisten di folder host `./data/` di VPS Anda.

---

Saat membuat **New Web Service** di Render.com, sesuaikan konfigurasi berikut:

1. **Build Command:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Start Command (KRUSIAL ⚠️):**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
3. **Environment Variables (Wajib Diisi):**
   * `DASHBOARD_USERNAME`: `admin` (atau username pilihan Anda)
   * `DASHBOARD_PASSWORD`: `password_rahasia_anda`
   * `DATABASE_URL`: `sqlite+aiosqlite:///./live_peak.db`
   * `PYTHON_VERSION`: `3.12.0` (opsional untuk versi Python Render)


---

## 🏛️ Struktur Direktori Proyek

```text
live-peak/
├── app/
│   ├── main.py                     # Entry point FastAPI & lifespan setup
│   ├── core/                       # Config (.env), logger, & database SQLite connection
│   ├── models/                     # Pydantic domain models & SQLAlchemy ORM DB models
│   ├── services/                   # Business logic (Discovery, Ingestion, Analytics, Merger, Manager, AutoTracker, Notification)
│   ├── api/                        # REST API endpoints, WebSockets, & Dashboard UI
│   └── utils/                      # Stats helpers, text helpers (stopwords), & mock replay
├── tests/                          # Pytest suite (Unit & Integration)
├── .env.example                    # Template variabel lingkungan
├── .gitignore                      # Mengabaikan .venv, *.db, .env, __pycache__
├── CODING_RULES.md                 # Standar pengodean & arsitektur proyek
├── TASKS.md                        # Task roadmap & status fitur
└── requirements.txt                # Dependensi Python proyek
```
