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

    <!-- TAB 3: PEAK REPORTS -->
    <div id="peak-reports" class="tab-content">
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>📑 Historical Peak Highlight Reports</h3>
                <button onclick="loadPeakReports()">🔄 Refresh Reports</button>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Video ID</th>
                        <th>Max Z-Score</th>
                        <th>Max Velocity</th>
                        <th>Total Chat</th>
                        <th>Keywords</th>
                        <th>Clip Start</th>
                        <th>Clip End</th>
                    </tr>
                </thead>
                <tbody id="reports-table-body">
                    <tr><td colspan="8" style="color: var(--text-muted);">Memuat data laporan...</td></tr>
                </tbody>
            </table>
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
            if (tabId === 'peak-reports') loadPeakReports();
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

        async function loadPeakReports() {
            const res = await fetch('/api/v1/peaks/');
            const data = await res.json();
            const tbody = document.getElementById('reports-table-body');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" style="color: var(--text-muted);">Belum ada laporan peak tercatat di database.</td></tr>';
                return;
            }

            data.forEach(p => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>#${p.id || '-'}</td>
                    <td><code>${p.video_id}</code></td>
                    <td><span class="badge">${p.max_z_score.toFixed(2)}</span></td>
                    <td>${p.max_chat_velocity.toFixed(1)} msg/s</td>
                    <td>${p.total_messages}</td>
                    <td>${p.highlight_keywords.join(', ') || '-'}</td>
                    <td>${new Date(p.padded_start_time).toLocaleTimeString()}</td>
                    <td>${new Date(p.padded_end_time).toLocaleTimeString()}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        initChart();
    </script>
</body>
</html>
"""

@router.get("/dashboard", response_class=HTMLResponse)
async def serve_protected_dashboard(username: str = Depends(authenticate_dashboard_user)):
    """Serves protected multi-tab interactive live monitoring dashboard."""
    return HTML_DASHBOARD_CONTENT
