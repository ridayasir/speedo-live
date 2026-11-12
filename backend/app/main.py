"""Speedo Live backend — ASGI application."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from .config import settings
from .db import get_db
from .http import api, client_ip, json_error
from .realtime import hub
from .security import rate_limiter

from .api import account, admin, complaints, driver, public  # noqa: F401  (registers routes)
from .api.public import live_websocket

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("speedo")


# ------------------------------------------------------------ middleware
class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                for k, v in ((b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                             (b"referrer-policy", b"strict-origin-when-cross-origin"),
                             (b"permissions-policy", b"geolocation=(self), camera=(), microphone=()")):
                    headers.append((k, v))
                if settings.env == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                # Web app files (html/css/js/svg): always revalidate so design updates show without a hard refresh
                if not scope["path"].startswith(("/api/", "/ws")) and not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-cache"))
            await send(message)
        await self.app(scope, receive, send_wrapper)


class GlobalRateLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/") and not scope["path"].startswith("/api/live/"):
            req = Request(scope)
            ok, retry = rate_limiter.allow(f"global:{client_ip(req)}", settings.rate_limit_per_min)
            if not ok:
                resp = json_error(429, "rate_limited", "Too many requests. Try again shortly.", headers={"Retry-After": str(retry)})
                return await resp(scope, receive, send)
        await self.app(scope, receive, send)


# ------------------------------------------------------------ background
async def _loop(name: str, interval: float, fn, *args):
    while True:
        try:
            await asyncio.to_thread(fn, *args)
        except Exception:
            log.exception("background task %s failed", name)
        await asyncio.sleep(interval)


def startup_sync() -> None:
    settings.validate()
    db = get_db()
    applied = db.migrate()
    if applied:
        log.info("migrations applied: %s", ", ".join(applied))
    from .seed import bootstrap_admin, seed_demo
    bootstrap_admin()
    if settings.is_demo:
        seed_demo()
        from .services.simulator import simulator
        simulator.setup()


@contextlib.asynccontextmanager
async def lifespan(app):
    hub.bind(asyncio.get_running_loop())
    await asyncio.to_thread(startup_sync)
    tasks = []
    if os.environ.get("SPEEDO_DISABLE_BACKGROUND") != "1":
        from .services import notify, tracking
        tasks += [
            asyncio.create_task(_loop("status", 10, tracking.status_sweep)),
            asyncio.create_task(_loop("watches", 15, notify.watch_sweep)),
            asyncio.create_task(_loop("delays", 30, notify.delay_sweep)),
            asyncio.create_task(_loop("retention", 3600, tracking.purge_old_locations)),
        ]
        if settings.is_demo:
            from .services.simulator import simulator
            tasks.append(asyncio.create_task(_loop("simulator", settings.sim_interval_s, simulator.step)))
        elif settings.gps_source == "provider" and settings.gps_provider_url:
            from .services.provider import poll_once
            tasks.append(asyncio.create_task(_loop("provider", settings.gps_interval_s, poll_once)))
    log.info("Speedo Live started in %s mode (%s)", settings.mode.upper(), "postgres" if settings.is_postgres else "sqlite")
    yield
    for t in tasks:
        t.cancel()


# ------------------------------------------------------------ misc routes
SWAGGER_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Speedo Live API</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="ui"></div><script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: '/openapi.json', dom_id: '#ui', persistAuthorization: true});</script></body></html>"""


async def openapi_json(request):
    return JSONResponse(api.openapi())


async def docs(request):
    return HTMLResponse(SWAGGER_HTML)


async def health(request):
    def check():
        get_db().scalar("SELECT 1")
        return True
    try:
        ok = await asyncio.to_thread(check)
    except Exception:
        ok = False
    return JSONResponse({"status": "ok" if ok else "degraded", "database": ok, "mode": settings.mode},
                        status_code=200 if ok else 503)


def _web(path: str):
    async def page(request):
        return FileResponse(os.path.join(settings.web_dir, path))
    return page


async def not_found_api(request):
    return json_error(404, "not_found", "No such endpoint")


routes = [
    *api.starlette_routes(),
    Route("/api/{rest:path}", not_found_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
    WebSocketRoute("/ws/live", live_websocket),
    Route("/openapi.json", openapi_json),
    Route("/docs", docs),
    Route("/health", health),
]
if os.path.isdir(settings.web_dir):
    routes += [
        Route("/admin", _web("admin.html")), Route("/driver", _web("driver.html")),
        Mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web"),
    ]

middleware = [Middleware(SecurityHeaders), Middleware(GlobalRateLimit)]
if settings.cors_origins:
    middleware.append(Middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                                 allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"]))

app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
