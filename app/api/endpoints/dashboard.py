import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from app.core.config import settings

router = APIRouter(tags=["Dashboard"])
security = HTTPBasic()


def authenticate_dashboard_user(credentials: HTTPBasicCredentials = Depends(security)):
    """Validates HTTP Basic Auth credentials against .env settings."""
    is_correct_username = secrets.compare_digest(credentials.username, settings.DASHBOARD_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect Dashboard Username or Password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


HTML_DASHBOARD_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Peak & Highlight Analytics Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --accent-color: #38bdf8;
            --peak-color: #ef4444;
            --success-color: #10b981;
            --text-color: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
        }
        body {
            margin: 0;
            padding: 0;
            font-family: system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
        }
        .navbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            background-color: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
        }
        .navbar h1 { margin: 0; font-size: 20px; color: var(--accent-color); }
        .nav-tabs {
            display: flex;
            gap: 12px;
            padding: 16px 24px 0 24px;
            border-bottom: 1px solid var(--border-color);
            background: #111827;
        }
        .tab-btn {
            padding: 10px 18px;
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            border-bottom: 2px solid transparent;
        }
        .tab-btn.active {
            color: var(--accent-color);
            border-bottom-color: var(--accent-color);
        }
        .tab-content {
            padding: 24px;
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 360px;
            gap: 24px;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
        }
        .input-group {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }
        input, button {
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            background: #0f172a;
            color: #fff;
            font-size: 14px;
        }
        button {
            background: #0284c7;
            cursor: pointer;
            border: none;
            font-weight: 600;
        }
        button:hover { background: #0369a1; }
        button.btn-danger { background: #dc2626; }
        button.btn-danger:hover { background: #b91c1c; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }
        th, td {
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid var(--border-color);
            font-size: 14px;
        }
        th { color: var(--text-muted); font-weight: 600; }
        .badge {
            background: rgba(239, 68, 68, 0.2);
            color: #f87171;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }
        .badge-success {
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
        }
        /* Modal Styles */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            z-index: 999;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(4px);
        }
        .modal-overlay.active {
            display: flex;
        }
        .modal-content {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            width: 90%;
            max-width: 820px;
            overflow: hidden;
            box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 20px;
            border-bottom: 1px solid var(--border-color);
        }
        .modal-header h3 {
            margin: 0;
            font-size: 16px;
        }
        .modal-close-btn {
            background: transparent;
            border: none;
            font-size: 26px;
            color: var(--text-muted);
            cursor: pointer;
            padding: 0 6px;
            line-height: 1;
        }
        .modal-close-btn:hover {
            color: #fff;
        }
        .video-container {
            position: relative;
            padding-bottom: 56.25%; /* 16:9 Aspect Ratio */
            height: 0;
            overflow: hidden;
            background: #000;
        }
        .video-container iframe {
            position: absolute;
            top: 0; left: 0;
            width: 100%; height: 100%;
            border: 0;
        }
        .modal-footer {
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #0b1120;
            font-size: 13px;
            color: var(--text-muted);
        }
        /* Filter and Pagination Styles */
        .filter-bar {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 16px 0;
            padding: 14px;
            background: #0f172a;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            align-items: center;
        }
        .filter-bar input, .filter-bar select {
            padding: 8px 12px;
            font-size: 13px;
            border-radius: 6px;
            border: 1px solid var(--border-color);
            background: #1e293b;
            color: #fff;
        }
        .pagination-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 16px;
            padding-top: 12px;
            border-top: 1px solid var(--border-color);
            flex-wrap: wrap;
            gap: 10px;
        }
        .pagination-controls {
            display: flex;
            align-items: center;
            gap: 8px;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>📊 YouTube Live Highlight & Peak Analyzer</h1>
        <div id="status-indicator">Status: Ready</div>
    </div>

    <div class="nav-tabs">
        <button class="tab-btn active" onclick="switchTab('live-monitor')">📈 Live Analytics & Monitoring</button>
        <button class="tab-btn" onclick="switchTab('channel-tracker')">📺 Auto-Tracked Channels</button>
        <button class="tab-btn" onclick="switchTab('peak-reports')">📑 Highlight Peak Reports</button>
    </div>

    <!-- TAB 1: LIVE MONITORING -->
    <div id="live-monitor" class="tab-content active">
        <div class="input-group">
            <input type="text" id="video-id-input" placeholder="Masukkan Video ID (misal: dQw4w9WgXcQ)" style="width: 340px;">
            <button onclick="startMonitoring()">Start Stream Monitoring</button>
            <button class="btn-danger" onclick="stopMonitoring()">Stop</button>
        </div>

        <div class="grid">
            <div class="card">
                <h3>Real-time Chat Velocity & Z-Score</h3>
                <canvas id="chart"></canvas>
            </div>
            <div class="card">
                <h3>🔥 Detected Highlight Peaks</h3>
                <div id="peaks-list" style="max-height: 400px; overflow-y: auto;">
                    <div style="color: var(--text-muted);">Belum ada peak terdeteksi...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- TAB 2: CHANNEL TRACKER -->
    <div id="channel-tracker" class="tab-content">
        <div class="card">
            <h3>📺 Auto-Tracked Channels (24/7 Monitoring)</h3>
            <p style="color: var(--text-muted); font-size: 14px;">
                Masukkan Nama Channel, @Handle (misal: @PUBGMOBILE), atau Channel ID di sini. Sistem akan otomatis melacak siaran langsungnya.
            </p>
            <div class="input-group">
                <input type="text" id="channel-id-input" placeholder="Masukkan @Handle atau Channel ID (misal: @PUBGMOBILE)" style="width: 420px;">
                <button onclick="addTrackedChannel()">Add Channel</button>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Channel Name</th>
                        <th>Channel ID</th>
                        <th>Status Tracking</th>
                        <th>Aksi</th>
                    </tr>
                </thead>
                <tbody id="channels-table-body">
                    <tr><td colspan="4" style="color: var(--text-muted);">Memuat daftar channel...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- TAB 3: VIDEO HIGHLIGHT REPORTS -->
    <div id="peak-reports" class="tab-content">
        <div class="card">
            <!-- VIDEO LIST PANEL -->
            <div id="video-list-panel">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h3>📑 Video Highlight Reports</h3>
                    <button onclick="loadVideoReports(1)">🔄 Refresh Reports</button>
                </div>

                <!-- FILTER BAR -->
                <div class="filter-bar">
                    <label style="font-size: 13px; color: var(--text-muted);">Dari</label>
                    <input type="date" id="filter-start-date">
                    <label style="font-size: 13px; color: var(--text-muted);">Sampai</label>
                    <input type="date" id="filter-end-date">
                    <input type="text" id="filter-video-search" placeholder="Cari judul video..." style="width: 200px;">
                    <select id="filter-sort-by">
                        <option value="video_date">Urutkan: Tanggal Video</option>
                        <option value="peak_count">Urutkan: Jumlah Peak</option>
                        <option value="max_z_score">Urutkan: Z-Score Tertinggi</option>
                        <option value="total_messages">Urutkan: Total Pesan</option>
                    </select>
                    <select id="filter-sort-order">
                        <option value="desc">Menurun (Desc)</option>
                        <option value="asc">Menaik (Asc)</option>
                    </select>
                    <button style="padding: 8px 14px;" onclick="applyVideoFilters()">🔍 Filter</button>
                    <button style="padding: 8px 14px; background: #334155;" onclick="resetVideoFilters()">↺ Reset</button>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th>Video</th>
                            <th>Channel</th>
                            <th>Tanggal</th>
                            <th>Jumlah Peak</th>
                            <th>Max Z-Score</th>
                            <th>Total Chat</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="videos-table-body">
                        <tr><td colspan="7" style="color: var(--text-muted);">Memuat daftar video...</td></tr>
                    </tbody>
                </table>

                <!-- PAGINATION BAR -->
                <div class="pagination-bar">
                    <div id="pagination-info" style="font-size: 13px; color: var(--text-muted);">
                        Menampilkan 0 dari 0 video
                    </div>
                    <div class="pagination-controls">
                        <span style="font-size: 13px; color: var(--text-muted);">Per Halaman:</span>
                        <select id="filter-page-size" onchange="changePageSize()" style="padding: 6px 10px; background: #1e293b; color: #fff; border: 1px solid var(--border-color); border-radius: 6px;">
                            <option value="10">10</option>
                            <option value="20" selected>20</option>
                            <option value="50">50</option>
                            <option value="100">100</option>
                        </select>
                        <button id="btn-prev-page" style="padding: 6px 12px; font-size: 12px; background: #1e293b;" onclick="prevVideoPage()" disabled>◀ Prev</button>
                        <span id="pagination-current-page" style="font-size: 13px; font-weight: 600; padding: 0 4px;">Halaman 1 / 1</span>
                        <button id="btn-next-page" style="padding: 6px 12px; font-size: 12px; background: #1e293b;" onclick="nextVideoPage()" disabled>Next ▶</button>
                    </div>
                </div>
            </div>

            <!-- VIDEO DETAIL PANEL -->
            <div id="video-detail-panel" style="display: none;">
                <button style="padding: 8px 14px; background: #334155;" onclick="closeVideoDetail()">← Kembali ke daftar video</button>
                <h3 id="video-detail-title" style="margin-top: 16px;"></h3>
                <div id="video-detail-meta" style="color: var(--text-muted); font-size: 13px; margin-bottom: 12px;"></div>

                <table>
                    <thead>
                        <tr>
                            <th>Menit</th>
                            <th>Range</th>
                            <th>Jumlah Peak</th>
                            <th>Max Z-Score</th>
                            <th>Max Velocity</th>
                            <th>Total Chat</th>
                            <th>Keywords</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="minutes-table-body"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        let chart;
        let ws;

        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');

            if (tabId === 'channel-tracker') loadTrackedChannels();
            if (tabId === 'peak-reports') loadVideoReports();
        }

        function initChart() {
            const ctx = document.getElementById('chart').getContext('2d');
            chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Chat Velocity (msg/s)',
                            data: [],
                            borderColor: '#38bdf8',
                            tension: 0.3
                        },
                        {
                            label: 'Z-Score Threshold',
                            data: [],
                            borderColor: '#ef4444',
                            borderDash: [5, 5],
                            tension: 0
                        }
                    ]
                },
                options: { responsive: true, scales: { y: { beginAtZero: true } } }
            });
        }

        async function startMonitoring() {
            const videoId = document.getElementById('video-id-input').value.trim();
            if (!videoId) return alert("Masukkan Video ID!");
            await fetch(`/api/v1/streams/start/${videoId}`, { method: 'POST' });
            connectWebSocket(videoId);
        }

        async function stopMonitoring() {
            const videoId = document.getElementById('video-id-input').value.trim();
            if (videoId) await fetch(`/api/v1/streams/stop/${videoId}`, { method: 'POST' });
            if (ws) ws.close();
        }

        function connectWebSocket(videoId) {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/live/${videoId}`);
            ws.onopen = () => {
                document.getElementById('status-indicator').innerText = `Status: Live Monitored (${videoId})`;
            };
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.status === 'waiting') return;

                const timeStr = new Date(data.window_end).toLocaleTimeString();
                chart.data.labels.push(timeStr);
                chart.data.datasets[0].data.push(data.chat_velocity);
                chart.data.datasets[1].data.push(2.5);

                if (chart.data.labels.length > 30) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                    chart.data.datasets[1].data.shift();
                }
                chart.update();

                if (data.is_peak) addPeakItem(data);
            };
        }

        function addPeakItem(data) {
            const list = document.getElementById('peaks-list');
            if (list.children.length === 1 && list.children[0].innerText.includes('Belum ada')) list.innerHTML = '';
            const div = document.createElement('div');
            div.style.padding = '12px';
            div.style.borderBottom = '1px solid var(--border-color)';
            div.innerHTML = `
                <div><span class="badge">PEAK DETECTED</span> <strong>Z-Score: ${data.z_score.toFixed(2)}</strong></div>
                <div style="font-size: 13px; color: var(--text-muted); margin-top: 4px;">
                    Velocity: ${data.chat_velocity.toFixed(1)} msg/s | Keywords: ${data.top_keywords.join(', ')}
                </div>
            `;
            list.prepend(div);
        }

        async function loadTrackedChannels() {
            const res = await fetch('/api/v1/channels/');
            const data = await res.json();
            const tbody = document.getElementById('channels-table-body');
            tbody.innerHTML = '';

            if (!data.channels || data.channels.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="color: var(--text-muted);">Belum ada channel yang di-track.</td></tr>';
                return;
            }

            data.channels.forEach(ch => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${ch.channel_name}</strong></td>
                    <td><code>${ch.channel_id}</code></td>
                    <td><span class="badge badge-success">AUTO-TRACKING ACTIVE</span></td>
                    <td><button class="btn-danger" style="padding: 6px 12px; font-size: 12px;" onclick="removeTrackedChannel('${ch.channel_id}')">Remove</button></td>
                `;
                tbody.appendChild(tr);
            });
        }

        async function addTrackedChannel() {
            const input = document.getElementById('channel-id-input').value.trim();
            if (!input) return alert("Masukkan @Handle atau Channel ID!");
            await fetch(`/api/v1/channels/track/${encodeURIComponent(input)}`, { method: 'POST' });
            document.getElementById('channel-id-input').value = '';
            loadTrackedChannels();
        }

        async function removeTrackedChannel(cid) {
            await fetch(`/api/v1/channels/untrack/${encodeURIComponent(cid)}`, { method: 'DELETE' });
            loadTrackedChannels();
        }

        let currentVideoPage = 1;
        let totalVideoPages = 1;

        function escapeHtml(value) {
            return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[ch]));
        }

        async function loadVideoReports(page = currentVideoPage) {
            currentVideoPage = Math.max(1, page);
            const startDate = document.getElementById('filter-start-date').value;
            const endDate = document.getElementById('filter-end-date').value;
            const search = document.getElementById('filter-video-search').value.trim();
            const sortBy = document.getElementById('filter-sort-by').value;
            const sortOrder = document.getElementById('filter-sort-order').value;
            const pageSize = parseInt(document.getElementById('filter-page-size').value, 10) || 20;

            const params = new URLSearchParams({
                page: currentVideoPage,
                page_size: pageSize,
                sort_by: sortBy,
                sort_order: sortOrder
            });
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);
            if (search) params.append('search', search);

            const res = await fetch(`/api/v1/videos/?${params.toString()}`);
            const data = await res.json();
            const tbody = document.getElementById('videos-table-body');
            tbody.innerHTML = '';

            const items = data.items || [];
            totalVideoPages = data.total_pages || 1;
            const total = data.total || 0;

            if (items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="color: var(--text-muted); text-align: center; padding: 24px;">Tidak ada video yang cocok dengan filter.</td></tr>';
            } else {
                items.forEach(v => {
                    const tr = document.createElement('tr');
                    const dateStr = v.started_at ? new Date(v.started_at).toLocaleString() : '-';
                    const liveBadge = v.is_live ? ' <span class="badge badge-success">LIVE</span>' : '';
                    tr.innerHTML = `
                        <td>
                            <strong>${escapeHtml(v.title)}</strong>${liveBadge}
                            <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;"><code>${escapeHtml(v.video_id)}</code></div>
                        </td>
                        <td><code>${escapeHtml(v.channel_id || '-')}</code></td>
                        <td>${dateStr}</td>
                        <td><span class="badge">${v.peak_count}</span></td>
                        <td>${v.max_z_score.toFixed(2)}</td>
                        <td>${v.total_messages}</td>
                        <td><button style="padding: 6px 12px; font-size: 12px;" onclick="openVideoDetail('${v.video_id}')">📂 Buka</button></td>
                    `;
                    tbody.appendChild(tr);
                });
            }

            const startEntry = total > 0 ? (currentVideoPage - 1) * pageSize + 1 : 0;
            const endEntry = Math.min(currentVideoPage * pageSize, total);
            document.getElementById('pagination-info').innerText = `Menampilkan ${startEntry} - ${endEntry} dari ${total} video`;
            document.getElementById('pagination-current-page').innerText = `Halaman ${currentVideoPage} / ${totalVideoPages}`;
            document.getElementById('btn-prev-page').disabled = currentVideoPage <= 1;
            document.getElementById('btn-next-page').disabled = currentVideoPage >= totalVideoPages;
        }

        async function openVideoDetail(videoId) {
            const res = await fetch(`/api/v1/videos/${encodeURIComponent(videoId)}`);
            if (!res.ok) {
                alert('Gagal memuat detail video.');
                return;
            }
            const data = await res.json();

            document.getElementById('video-list-panel').style.display = 'none';
            document.getElementById('video-detail-panel').style.display = 'block';

            document.getElementById('video-detail-title').innerText = data.title;
            const started = data.started_at ? new Date(data.started_at).toLocaleString() : '-';
            const ended = data.ended_at ? new Date(data.ended_at).toLocaleString() : '-';
            document.getElementById('video-detail-meta').innerText =
                `${data.video_id} • ${data.peak_count} peak • Max Z-Score ${data.max_z_score.toFixed(2)} • ${data.total_messages} chat • ${started} s/d ${ended}`;

            const tbody = document.getElementById('minutes-table-body');
            tbody.innerHTML = '';

            const minutes = data.minutes || [];
            if (minutes.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" style="color: var(--text-muted); text-align: center; padding: 24px;">Belum ada peak pada video ini.</td></tr>';
                return;
            }

            minutes.forEach(m => {
                const best = m.peaks.reduce((a, b) => (b.max_z_score > a.max_z_score ? b : a), m.peaks[0]);
                const sSec = best.start_offset_seconds != null ? Math.floor(best.start_offset_seconds) : Math.floor(m.start_offset_seconds);
                const eSec = best.end_offset_seconds != null ? Math.ceil(best.end_offset_seconds) : Math.ceil(m.end_offset_seconds);
                const timeLabel = (best.video_start_time && best.video_end_time)
                    ? `${best.video_start_time} - ${best.video_end_time}`
                    : `${sSec}s - ${eSec}s`;

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${m.minute_label}</strong></td>
                    <td>${sSec}s - ${eSec}s</td>
                    <td><span class="badge">${m.peak_count}</span></td>
                    <td>${m.max_z_score.toFixed(2)}</td>
                    <td>${m.max_chat_velocity.toFixed(1)} msg/s</td>
                    <td>${m.total_messages}</td>
                    <td>${(m.highlight_keywords || []).join(', ') || '-'}</td>
                    <td>
                        <button style="padding: 6px 12px; font-size: 12px;" onclick="openClipModal('${data.video_id}', ${sSec}, ${eSec}, '${timeLabel}')">🎬 Review Clip</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function closeVideoDetail() {
            document.getElementById('video-detail-panel').style.display = 'none';
            document.getElementById('video-list-panel').style.display = 'block';
        }

        function applyVideoFilters() {
            loadVideoReports(1);
        }

        function resetVideoFilters() {
            document.getElementById('filter-start-date').value = '';
            document.getElementById('filter-end-date').value = '';
            document.getElementById('filter-video-search').value = '';
            document.getElementById('filter-sort-by').value = 'video_date';
            document.getElementById('filter-sort-order').value = 'desc';
            loadVideoReports(1);
        }

        function changePageSize() {
            loadVideoReports(1);
        }

        function prevVideoPage() {
            if (currentVideoPage > 1) {
                loadVideoReports(currentVideoPage - 1);
            }
        }

        function nextVideoPage() {
            if (currentVideoPage < totalVideoPages) {
                loadVideoReports(currentVideoPage + 1);
            }
        }

        function openClipModal(videoId, startSec, endSec, timeLabel) {
            const modal = document.getElementById('clip-modal');
            const iframe = document.getElementById('clip-iframe');
            const title = document.getElementById('modal-title');
            const meta = document.getElementById('modal-meta');

            title.innerText = `🎬 Review Highlight Clip (${videoId})`;
            meta.innerText = `Range: ${timeLabel} (Detik: ${startSec}s - ${endSec}s)`;
            
            iframe.src = `https://www.youtube.com/embed/${encodeURIComponent(videoId)}?start=${startSec}&end=${endSec}&autoplay=1`;
            modal.classList.add('active');
        }

        function closeClipModal() {
            const modal = document.getElementById('clip-modal');
            const iframe = document.getElementById('clip-iframe');
            iframe.src = '';
            modal.classList.remove('active');
        }

        function handleBackdropClick(event) {
            if (event.target.id === 'clip-modal') {
                closeClipModal();
            }
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeClipModal();
        });

        initChart();
    </script>

    <!-- MODAL REVIEW CLIP -->
    <div id="clip-modal" class="modal-overlay" onclick="handleBackdropClick(event)">
        <div class="modal-content">
            <div class="modal-header">
                <h3 id="modal-title">🎬 Review Highlight Clip</h3>
                <button class="modal-close-btn" onclick="closeClipModal()">&times;</button>
            </div>
            <div class="video-container">
                <iframe id="clip-iframe" src="" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
            </div>
            <div class="modal-footer">
                <span id="modal-meta">Range: -</span>
                <button style="padding: 6px 12px; font-size: 12px;" onclick="closeClipModal()">Tutup</button>
            </div>
        </div>
    </div>
</body>
</html>
"""

@router.get("/dashboard", response_class=HTMLResponse)
async def serve_protected_dashboard(username: str = Depends(authenticate_dashboard_user)):
    """Serves protected multi-tab interactive live monitoring dashboard."""
    return HTML_DASHBOARD_CONTENT
