"""Vercel entry point: runs the Speedo Live app as a serverless function.

Serverless functions only run while answering a request, so there are no background loops:
- the database is SQLite in /tmp (rebuilt with the demo network on each cold start),
- the bus simulator advances on incoming requests by the time that passed since the last one,
- the SSE stream / WebSocket are refused, so the web app falls back to polling /api/buses.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys
import threading
import time
from urllib.parse import parse_qsl, quote, urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/speedo.db")
os.environ.setdefault("SPEEDO_MODE", "demo")
os.environ.setdefault("APP_ENV", "production")
os.environ.setdefault("TRUST_PROXY", "true")
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("WEB_DIR", os.path.join(ROOT, "web", "public"))
os.environ.setdefault("SPEEDO_ENV_FILE", "/nonexistent")
os.environ["SPEEDO_DISABLE_BACKGROUND"] = "1"
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.config import settings  # noqa: E402
from app.main import app as speedo_app, startup_sync  # noqa: E402

_init_lock = threading.Lock()
_tick_lock = threading.Lock()
_ready = False
_last_tick = 0.0
MAX_CATCH_UP_S = 120.0


def _ensure_started() -> None:
    global _ready, _last_tick
    with _init_lock:
        if not _ready:
            startup_sync()
            _last_tick = time.monotonic() - settings.sim_interval_s  # first request already places the buses
            _ready = True


def _tick() -> None:
    """Advance the demo simulator by the time since the last request (non-blocking if busy)."""
    global _last_tick
    if not _tick_lock.acquire(blocking=False):
        return
    try:
        now = time.monotonic()
        elapsed = now - _last_tick
        if elapsed < settings.sim_interval_s:
            return
        _last_tick = now
        from app.services import tracking
        from app.services.simulator import simulator
        simulator.step(min(elapsed, MAX_CATCH_UP_S))  # step() applies SIM_TIME_SCALE itself
        tracking.status_sweep()
    finally:
        _tick_lock.release()


def _original_path(scope):
    """vercel.json rewrites every URL to /api/index?__p=<original path>; put the original path back."""
    pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
    if not any(k == "__p" for k, _ in pairs):
        return scope
    orig = "/" + next(v for k, v in pairs if k == "__p").lstrip("/")
    rest = urlencode([(k, v) for k, v in pairs if k != "__p"])
    return {**scope, "path": orig, "raw_path": quote(orig).encode(), "query_string": rest.encode("latin-1")}


async def app(scope, receive, send):
    if scope["type"] == "lifespan":  # nothing to start: work happens lazily per request
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1013})
        return
    scope = _original_path(scope)
    await asyncio.to_thread(_ensure_started)
    path = scope.get("path", "")
    if path == "/api/live/stream":  # long-lived streams don't fit serverless; the client then polls
        body = b'{"error":{"code":"stream_unavailable","message":"Live stream not available here; poll /api/buses"}}'
        await send({"type": "http.response.start", "status": 503,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
        return
    if settings.is_demo and (path.startswith("/api/") or path == "/health"):
        await asyncio.to_thread(_tick)
    await speedo_app(scope, receive, send)
