# Agent Context: YouTube Live Highlight & Peak Data Analyzer

## 1. Project Overview
Project ini adalah **Data Analytics Pipeline** ringan yang bertugas memantau siaran langsung YouTube secara real-time, menyedot aliran pesan chat, menganalisis volatilitas obrolan (*chat velocity*), dan mendeteksi titik puncak momen menarik (*highlights/peaks*) menggunakan pendekatan statistik.

> **Catatan:** Project ini **TIDAK** memproses, mengunduh, memotong, atau mengedit berkas video/FFmpeg. Project ini hanya berfokus pada ekstraksi data, perhitungan statistik real-time, dan penyimpanan data terstruktur.

---

## 2. Tech Stack & Recommended Libraries
- **Language:** Python 3.10+ / Node.js (TypeScript)
- **Discovery Phase:** RSS Feeds (`/feeds/videos.xml?channel_id=...`) atau Passive HTTP Polling ke URL `/live`.
- **Chat Ingestion:** `pytchat` atau `chat-downloader` (WebSocket / InnerTube API tanpa Selenium).
- **Data Processing & Analytics:** `pandas`, `numpy`, atau pustaka kalkulasi statistik native.
- **Database / Output:** PostgreSQL, SQLite, atau MongoDB (Simpan hasil JSON terstruktur).

---

## 3. System Architecture & Flow

```text
[ Saluran Target ] 
       │
       ▼ (Polling Pasif / RSS)
[ 1. Discovery ] ──► Mendeteksi Status Live Stream Active
       │
       ▼ (Inisialisasi Listener)
[ 2. Chat Ingestion ] ──► Stream Live Chat Real-time (pytchat)
       │
       ▼ (Aggregator per 10 Detik)
[ 3. Sliding Window ] ──► Hitung Chat Velocity & Filter Kata Kunci/Emoji
       │
       ▼ (Kalkulasi Statistik)
[ 4. Event Detection ] ──► Z-Score Peak Detection Algorithm
       │
       ▼ (Merging & Padding)
[ 5. Data Structuring ] ──► Gabung Peak Berdekatan & Format Output
       │
       ▼
[ Output API / Database / Notification ]