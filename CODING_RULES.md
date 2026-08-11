# 📏 Coding Rules & Architecture Guidelines

Dokumen ini berisi standar pengodean, arsitektur sistem, dan pedoman desain untuk memastikan kode proyek **YouTube Live Highlight & Peak Data Analyzer** dapat dibaca dengan nyaman (*clean code*), mudah dipelihara (*maintainable*), dan mudah diuji (*testable*).

---

## 🏛️ 1. Arsitektur Proyek (Layered Architecture)

Proyek menggunakan pola **Separation of Concerns** di mana setiap lapisan hanya bertanggung jawab atas fungsinya sendiri:

```text
live-peak/
├── app/
│   ├── __init__.py
│   ├── main.py                     # Entry point FastAPI & manajemen lifespan asyncio
│   ├── core/                       # Konfigurasi global, logger, & database connection
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings & environment variables
│   │   ├── logger.py               # Setup structured logging
│   │   └── database.py             # Koneksi Async Database (SQLite / PostgreSQL)
│   ├── models/                     # Skema data (Domain models & DB models)
│   │   ├── __init__.py
│   │   ├── domain.py               # Pydantic schemas (ChatMessage, PeakEvent, WindowStats)
│   │   └── db.py                   # Async ORM / Database models
│   ├── services/                   # Business Logic & Core Pipeline Services
│   │   ├── __init__.py
│   │   ├── discovery.py            # Stream Discovery Service (RSS / Passive Polling)
│   │   ├── ingestion.py            # Chat Ingestion Service (pytchat listener & manager)
│   │   ├── analytics.py            # Sliding Window Aggregator & Z-Score Peak Detector
│   │   └── merger.py               # Peak Merging & Time Padding Service
│   ├── api/                        # Transport Layer (REST API & WebSockets)
│   │   ├── __init__.py
│   │   ├── router.py               # Central API Router
│   │   └── endpoints/
│   │       ├── streams.py          # Endpoints status live stream
│   │       ├── peaks.py            # Endpoints query data highlight/peak
│   │       └── websocket.py        # Real-time WebSocket stream untuk dashboard
│   └── utils/                      # Pure Helper Functions
│       ├── __init__.py
│       └── stats_helpers.py        # Fungsi statistik murni (Z-score calculation, rolling window)
├── tests/                          # Pytest suite
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── .env.example
├── pyproject.toml
├── AGENTS.md
├── CODING_RULES.md
├── TASKS.md
└── README.md
```

---

## 📐 2. Prinsip & Standar Pengodean

### A. Modularisasi & Prinsip SOLID
1. **Single Responsibility Principle (SRP):** Setiap modul/berkas hanya bertanggung jawab atas satu fungsi.
   * `ingestion.py` *hanya* menarik pesan chat dari YouTube API.
   * `analytics.py` *hanya* menghitung statistik dan Z-score.
   * `merger.py` *hanya* menggabungkan peak yang berdekatan.
2. **Functional Core, Imperative Shell:**
   * Algoritma perhitungan (perhitungan Z-Score dan *sliding window*) wajib berada di `app/utils/stats_helpers.py` sebagai **Pure Functions** tanpa *side effect*. Hal ini memungkinkan unit testing cepat tanpa mocking.

### B. Type Hinting & Validasi Data Strict (Python 3.10+)
1. **Gunakan Type Annotations eksplisit di setiap fungsi:**
   ```python
   # WAJIB ✅
   def calculate_z_score(velocity: float, mean: float, std_dev: float) -> float:
       if std_dev == 0.0:
           return 0.0
       return (velocity - mean) / std_dev
   ```
2. **Gunakan Pydantic Model untuk Inter-service Data Passing:**
   Semua pertukaran data antar *service* harus dikemas menggunakan Pydantic Model di `app/models/domain.py` (hindari `dict` mentah).

### C. Pemrosesan Asinkron (`asyncio`)
1. **Strict Non-blocking Operations:**
   * Jangan gunakan `time.sleep()`, gunakan `await asyncio.sleep()`.
   * Gunakan HTTP client asinkron (`httpx` atau `aiohttp`).
2. **Manajemen Lifespan FastAPI:**
   * Jalankan background worker (seperti discovery & listener) via `asyncio.create_task` di dalam `@asynccontextmanager lifespan` di `app/main.py`.

### D. Error Handling & Logging
1. **Structured Logging:**
   * Gunakan logger terpusat (`app/core/logger.py`), larang penggunaan `print()`.
2. **Resilient Stream Connection:**
   * Jika koneksi chat YouTube terputus, tangkap exception, catat warning log, dan lakukan *exponential backoff retry* tanpa menghentikan *service* utama.

### E. Manajemen Konfigurasi
1. Semua parameter ambang batas (*threshold* Z-Score), durasi window (misal 10 detik), dan URL database **wajib** dikelola melalui `app/core/config.py` menggunakan `pydantic-settings` yang membaca dari berkas `.env`.
