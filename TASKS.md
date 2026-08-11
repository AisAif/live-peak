# 📋 Task Roadmap: YouTube Live Highlight & Peak Data Analyzer

Dokumen ini berisi daftar tugas (*task list*) dan tahapan eksekusi proyek secara terstruktur.

---

## 🎯 Phase 1: Setup Proyek & Konfigurasi Dasar
> **Fokus:** Menyiapkan struktur direktori, manajemen dependency, konfigurasi environment, dan model domain data.

- [x] **Task 1.1:** Buat struktur direktori proyek (`app/core`, `app/models`, `app/services`, `app/api`, `app/utils`, `tests`).
- [x] **Task 1.2:** Inisialisasi `pyproject.toml` / `requirements.txt` dengan dependency utama (FastAPI, Uvicorn, pytchat, Pydantic v2, numpy, pytest, httpx, pydantic-settings).
- [x] **Task 1.3:** Buat modul konfigurasi terpusat `app/core/config.py` (Z-score threshold, sliding window duration, log level).
- [x] **Task 1.4:** Definisikan skema Pydantic domain di `app/models/domain.py` (`ChatMessage`, `WindowStats`, `PeakEvent`, `StreamInfo`).
- [x] **Task 1.5:** Buat setup structured logging di `app/core/logger.py`.

---

## ⚡ Phase 2: Analytics & Peak Detection Engine
> **Fokus:** Mengimplementasikan fungsi murni algoritma statistik Z-Score, analisis emoji/kata kunci, simulator mock data, dan unit test-nya.

- [x] **Task 2.1:** Implementasikan helper statistik murni di `app/utils/stats_helpers.py` (kalkulasi Z-score, rolling mean, rolling std_dev).
- [x] **Task 2.2:** Buat `app/services/analytics.py` untuk agregator sliding window (default 10 detik).
- [x] **Task 2.3:** Buat `app/services/merger.py` untuk penggabungan peak berdekatan (*merging*) dan penambahan *time padding*.
- [x] **Task 2.4:** Ekstraktor Emoji & Keyword Volatility di `app/utils/text_helpers.py` untuk mengidentifikasi kata/emoji dominan saat puncak.
- [x] **Task 2.5:** Simulator Mock Chat Data di `app/utils/mock_replay.py` untuk pengujian offline algoritma Z-score tanpa menunggu live stream asli.
- [x] **Task 2.6:** Buat *Unit Test* di `tests/unit/test_stats_helpers.py`, `tests/unit/test_analytics.py`, `tests/unit/test_merger.py`.

---

## 📡 Phase 3: Discovery & Chat Ingestion Pipeline
> **Fokus:** Mendeteksi siaran langsung, mengambil aliran pesan chat real-time, dan mengelola lifecycle multi-stream.

- [x] **Task 3.1:** Implementasikan `app/services/discovery.py` (Passive HTTP polling / RSS feed kanal YouTube target).
- [x] **Task 3.2:** Implementasikan `app/services/ingestion.py` sebagai *wrapper* `pytchat` yang mengalirkan data chat ke `analytics.py`.
- [x] **Task 3.3:** Buat `StreamManager` Service (`app/services/manager.py`) untuk mengontrol start/stop/status listener multi-stream secara asinkron.
- [x] **Task 3.4:** Tambahkan mekanisme *reconnection & exponential backoff* jika koneksi chat YouTube terputus.

---

## 💾 Phase 4: Storage, Webhooks & FastAPI Integration
> **Fokus:** Menyimpan data terstruktur, Webhook Notifikasi real-time, REST API, WebSockets, dan Live Chart Dashboard.

- [x] **Task 4.1:** Setup modul database async di `app/core/database.py` dan model DB di `app/models/db.py`.
- [x] **Task 4.2:** Buat `app/main.py` dengan manajemen *lifespan* untuk mengontrol background tasks.
- [x] **Task 4.3:** Implementasikan REST API endpoints di `app/api/endpoints/streams.py` dan `peaks.py`.
- [x] **Task 4.4:** Implementasikan WebSocket handler di `app/api/endpoints/websocket.py` untuk streaming data real-time.
- [x] **Task 4.5:** Implementasikan `NotificationService` (`app/services/notification.py`) untuk mengirim alert Webhook (Discord/Telegram/HTTP) saat peak terdeteksi.
- [x] **Task 4.6:** Buat Embedded Dashboard UI ringan (Chart.js real-time graph) di `app/api/endpoints/dashboard.py`.

---

## 🧪 Phase 5: Verification & End-to-End Testing
> **Fokus:** Pengujian menyeluruh dengan stream live aktif atau mock data dan finalisasi dokumentasi.

- [x] **Task 5.1:** Buat *integration test* API & WebSocket di `tests/integration/test_api.py`.
- [x] **Task 5.2:** Lakukan pengujian langsung dengan YouTube Live stream aktif / simulator dan *tuning* nilai Z-score threshold.
- [x] **Task 5.3:** Lengkapi `README.md` dengan instruksi cara menjalankan dan dokumentasi API.
