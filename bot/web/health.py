"""Tiny aiohttp health/metrics endpoint (also a friendly status page)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from aiohttp import web

from bot import __version__
from bot.config import Settings

if TYPE_CHECKING:  # pragma: no cover
    from bot.services.downloader.manager import DownloadManager

log = logging.getLogger(__name__)

_DASHBOARD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TELRO · online</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: radial-gradient(1200px 600px at 20% 0%, #1b2a5b 0%, #0a0f1f 45%, #06080f 100%);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; color: #e8eeff;
  }}
  .card {{
    width: min(92vw, 520px); padding: 34px; border-radius: 24px;
    background: linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.02));
    border: 1px solid rgba(255,255,255,.12); box-shadow: 0 30px 80px rgba(0,0,0,.5);
    text-align: center; backdrop-filter: blur(14px);
  }}
  .logo {{
    width: 82px; height: 82px; margin: 0 auto 18px; border-radius: 22px;
    display: grid; place-items: center; font-size: 40px;
    background: linear-gradient(135deg, #5b8cff, #8b5cf6 55%, #ec4899);
    box-shadow: 0 16px 40px rgba(91,140,255,.35);
  }}
  h1 {{ margin: 0; font-size: 30px; letter-spacing: .18em; }}
  .tag {{ color: #9fb0d9; margin: 8px 0 26px; font-size: 14px; }}
  .status {{
    display: inline-flex; gap: 9px; align-items: center; padding: 9px 16px;
    border-radius: 999px; background: rgba(34,197,94,.12); border: 1px solid rgba(34,197,94,.35);
    color: #6ee7a8; font-weight: 650; font-size: 14px;
  }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 0 rgba(34,197,94,.6); animation: pulse 2s infinite; }}
  @keyframes pulse {{ 70% {{ box-shadow: 0 0 0 12px rgba(34,197,94,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(34,197,94,0); }} }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 28px; }}
  .stat {{ background: rgba(255,255,255,.045); border: 1px solid rgba(255,255,255,.08); border-radius: 14px; padding: 14px 8px; }}
  .stat b {{ display: block; font-size: 17px; }}
  .stat span {{ font-size: 11px; color: #8fa2cc; text-transform: uppercase; letter-spacing: .08em; }}
  .foot {{ margin-top: 24px; font-size: 12px; color: #7b8cb5; }}
  .foot a {{ color: #93b4ff; text-decoration: none; }}
</style>
</head>
<body>
  <main class="card">
    <div class="logo">✈️</div>
    <h1>TELRO</h1>
    <p class="tag">downloads · music · AI · images</p>
    <div class="status"><span class="dot"></span> Bot is online</div>
    <div class="grid">
      <div class="stat"><b id="uptime">—</b><span>uptime</span></div>
      <div class="stat"><b>{version}</b><span>version</span></div>
      <div class="stat"><b id="jobs">0</b><span>active jobs</span></div>
    </div>
    <p class="foot">Telegram: <a href="https://t.me/{username}">@{username}</a> · health endpoint <code>/health</code></p>
  </main>
  <script>
    const started = Date.now() - {uptime_seconds} * 1000;
    function fmt(s) {{
      const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
      return d ? d + "d " + h + "h" : h ? h + "h " + m + "m" : m + "m";
    }}
    setInterval(() => {{
      document.getElementById("uptime").textContent = fmt(Math.floor((Date.now() - started) / 1000));
    }}, 1000);
    fetch("/health").then(r => r.json()).then(d => {{
      document.getElementById("jobs").textContent = d.active_jobs ?? 0;
    }}).catch(() => {{}});
  </script>
</body>
</html>
"""


def build_app(
    cfg: Settings,
    started_at: float,
    manager: DownloadManager | None = None,
) -> web.Application:
    async def index(_: web.Request) -> web.Response:
        html = _DASHBOARD.format(
            version=__version__,
            username=(cfg.bot_username or "Rwinro_bot").lstrip("@"),
            uptime_seconds=int(time.time() - started_at),
        )
        return web.Response(text=html, content_type="text/html")

    async def health(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "version": __version__,
                "uptime_seconds": int(time.time() - started_at),
                "active_jobs": manager.active_count if manager else 0,
                "bot": f"@{cfg.bot_username}" if cfg.bot_username else None,
            }
        )

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/healthz", health)
    return app


async def start_health(
    cfg: Settings,
    started_at: float,
    manager: DownloadManager | None = None,
) -> web.AppRunner | None:
    app = build_app(cfg, started_at, manager)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=cfg.health_host, port=cfg.health_port)
    try:
        await site.start()
    except OSError as exc:
        log.warning("Health server could not bind %s:%s (%s)", cfg.health_host, cfg.health_port, exc)
        await runner.cleanup()
        return None
    log.info("Health server listening on http://%s:%s", cfg.health_host, cfg.health_port)
    return runner
