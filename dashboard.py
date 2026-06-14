"""
J.A.R.V.I.S Web Dashboard — FastAPI-based local web interface.

Provides system monitoring, conversation log viewing, and configuration
management through a browser interface.

Usage:
    from dashboard import start_dashboard
    start_dashboard(port=8080)
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn

    FASTAPI_AVAILABLE = True

    app = FastAPI(title="J.A.R.V.I.S Dashboard", version="1.0.0")
except ImportError:
    FASTAPI_AVAILABLE = False
    app = None  # type: ignore

BASE_DIR = Path(__file__).resolve().parent

# ── In-memory state ────────────────────────────────────────────────────
_started_at = time.time()
_conversation_log: list[dict] = []
_system_stats: dict = {}


def update_conversation(entry: dict) -> None:
    """Add an entry to the conversation log (thread-safe)."""
    _conversation_log.append({
        "timestamp": time.time(),
        **entry,
    })
    # Keep only last 200 entries
    while len(_conversation_log) > 200:
        _conversation_log.pop(0)


def update_stats(stats: dict) -> None:
    """Update system stats snapshot."""
    _system_stats.update(stats)


# ── Routes ─────────────────────────────────────────────────────────────


@app.get("/")
async def index() -> HTMLResponse:
    """Main dashboard page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>J.A.R.V.I.S Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #020c0c; color: #7dfff6; min-height: 100vh;
        }}
        .header {{
            background: #030f0f; border-bottom: 1px solid #006a62;
            padding: 16px 24px; display: flex; align-items: center; gap: 12px;
        }}
        .header h1 {{ color: #00d4c0; font-size: 20px; }}
        .header .badge {{
            background: #006a62; color: #7dfff6; padding: 2px 10px;
            border-radius: 12px; font-size: 11px;
        }}
        .grid {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
            padding: 20px;
        }}
        @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} }}
        .card {{
            background: #030f0f; border: 1px solid #006a62; border-radius: 8px;
            padding: 16px;
        }}
        .card h2 {{ color: #00d4c0; font-size: 14px; margin-bottom: 12px;
                     text-transform: uppercase; letter-spacing: 1px; }}
        .stat-row {{ display: flex; justify-content: space-between; padding: 6px 0;
                     border-bottom: 1px solid #0a2a28; font-size: 13px; }}
        .stat-row:last-child {{ border-bottom: none; }}
        .stat-label {{ color: #006a62; }}
        .stat-value {{ color: #00ff88; font-weight: 600; }}
        .log-entry {{ padding: 8px 0; border-bottom: 1px solid #0a2a28; font-size: 12px; }}
        .log-entry .time {{ color: #006a62; font-size: 11px; }}
        .log-entry .role-you {{ color: #d0f0ee; }}
        .log-entry .role-ai {{ color: #00d4c0; }}
        .log-entry .role-sys {{ color: #ffcc00; }}
        .full-width {{ grid-column: 1 / -1; }}
        .refresh {{ color: #006a62; font-size: 11px; margin-top: 8px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>J.A.R.V.I.S</h1>
        <span class="badge">ONLINE</span>
        <span class="badge">v{BASE_DIR.parent.joinpath('VERSION').read_text().strip() if (BASE_DIR.parent / 'VERSION').exists() else '1.0.0'}</span>
    </div>
    <div class="grid" id="app">
        <div class="card">
            <h2>System</h2>
            <div id="system-stats">Loading...</div>
        </div>
        <div class="card">
            <h2>Tools</h2>
            <div id="tool-count">Loading...</div>
        </div>
        <div class="card full-width">
            <h2>Conversation Log</h2>
            <div id="conversation-log">Loading...</div>
        </div>
    </div>
    <div class="refresh" style="text-align:center;padding:12px;">
        Auto-refreshes every 5 seconds
    </div>
    <script>
        async function refresh() {{
            try {{
                const [stats, health, log] = await Promise.all([
                    fetch('/api/stats').then(r => r.json()),
                    fetch('/api/health').then(r => r.json()),
                    fetch('/api/conversation').then(r => r.json()),
                ]);
                document.getElementById('system-stats').innerHTML =
                    Object.entries(stats).map(([k,v]) =>
                        `<div class="stat-row"><span class="stat-label">${{k}}</span><span class="stat-value">${{v}}</span></div>`
                    ).join('');
                document.getElementById('tool-count').innerHTML =
                    `<div class="stat-row"><span class="stat-label">Tools</span><span class="stat-value">${{health.tool_count}}</span></div>` +
                    `<div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value">${{health.uptime}}</span></div>` +
                    `<div class="stat-row"><span class="stat-label">Platform</span><span class="stat-value">${{health.platform}}</span></div>`;
                document.getElementById('conversation-log').innerHTML =
                    log.map(e =>
                        `<div class="log-entry">
                            <span class="time">${{new Date(e.timestamp*1000).toLocaleTimeString()}}</span>
                            <span class="role-${{e.role || 'sys'}}">${{e.text || e.message || ''}}</span>
                        </div>`
                    ).join('') || '<div class="stat-row">No entries yet.</div>';
            }} catch(e) {{
                console.error('Refresh failed:', e);
            }}
        }}
        refresh();
        setInterval(refresh, 5000);
    </script>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/api/health")
async def health() -> JSONResponse:
    """Health check endpoint."""
    from core.version import __version__ as jarvis_version

    uptime_seconds = int(time.time() - _started_at)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return JSONResponse({
        "status": "ok",
        "version": jarvis_version,
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "platform": platform.system(),
        "tool_count": _system_stats.get("tool_count", 0),
        "conversation_entries": len(_conversation_log),
    })


@app.get("/api/stats")
async def stats() -> JSONResponse:
    """System statistics endpoint."""
    try:
        import psutil
        current_stats = {
            "CPU": f"{psutil.cpu_percent(interval=0.1)}%",
            "RAM": f"{psutil.virtual_memory().percent}%",
            "Disk": f"{psutil.disk_usage('/').percent}%",
            "Battery": f"{psutil.sensors_battery().percent}%" if psutil.sensors_battery() else "N/A",
        }
    except Exception:
        current_stats = _system_stats

    current_stats["Python"] = platform.python_version()
    return JSONResponse(current_stats)


@app.get("/api/conversation")
async def conversation(limit: int = 50) -> JSONResponse:
    """Conversation log endpoint."""
    return JSONResponse(_conversation_log[-limit:])


@app.get("/api/config")
async def config() -> JSONResponse:
    """Show safe configuration values (keys redacted)."""
    try:
        from app_config import load_app_config
        cfg = load_app_config()
        # Redact sensitive values
        safe = {}
        for k, v in cfg.items():
            if isinstance(v, str) and any(secret in k.lower() for secret in ["key", "token", "secret", "password"]):
                safe[k] = v[:8] + "..." if len(v) > 8 else "***"
            else:
                safe[k] = v
        return JSONResponse(safe)
    except Exception:
        return JSONResponse({"error": "configuration_unavailable"})


# ── Server management ──────────────────────────────────────────────────

_server: uvicorn.Server | None = None
_server_thread: threading.Thread | None = None


def start_dashboard(host: str = "127.0.0.1", port: int = 8080, daemon: bool = True) -> dict[str, Any]:
    """
    Start the web dashboard server in a background thread.

    Args:
        host: Bind address (default: 127.0.0.1 for local-only).
        port: Port number (default: 8080).
        daemon: Run as daemon thread (auto-exits with main program).

    Returns:
        Dict with success, url, and any error message.
    """
    global _server, _server_thread

    if not FASTAPI_AVAILABLE:
        return {
            "success": False,
            "error": "FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn",
        }

    if _server is not None:
        return {"success": True, "url": f"http://{host}:{port}", "message": "Already running"}

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=daemon)
    _server_thread.start()

    return {
        "success": True,
        "url": f"http://{host}:{port}",
        "message": f"Dashboard started at http://{host}:{port}",
    }


def stop_dashboard() -> dict[str, Any]:
    """Stop the web dashboard server."""
    global _server, _server_thread
    if _server:
        _server.should_exit = True
        _server = None
        _server_thread = None
        return {"success": True, "message": "Dashboard stopped"}
    return {"success": False, "message": "Dashboard not running"}


def dashboard_status() -> dict[str, Any]:
    """Check if the dashboard is running."""
    return {
        "running": _server is not None,
        "fastapi_available": FASTAPI_AVAILABLE,
    }
