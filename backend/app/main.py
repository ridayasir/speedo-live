import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import firebase
from .config import get_settings
from .db import SessionLocal
from .limits import limiter
from .routers import admin, auth, complaints, driver, me, public, ws
from .services import gps_provider, monitor, on_request, simulator
from .services.realtime import hub
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("speedo")


class _RedactQuery(logging.Filter):
    """Keep what passengers search for, and where they are, out of the logs: drop URL query strings
    (place names, coordinates) from access and HTTP-client log lines (spec section 11)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            record.args = tuple(a.split("?", 1)[0] + ("?…" if "?" in a else "") if isinstance(a, str) else a
                                for a in record.args)
        return True


for _name in ("uvicorn.access", "httpx"):
    logging.getLogger(_name).addFilter(_RedactQuery())
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry the full place-search URL


def _run(fn):
    with SessionLocal() as db:
        return fn(db)


async def _loop(name: str, fn, every: float):
    while True:
        try:
            await asyncio.to_thread(_run, fn)
        except Exception:
            log.exception("background task %s failed", name)
        await asyncio.sleep(every)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if not s.serverless:  # serverless connects on the first request instead (see serverless_background)
        await asyncio.to_thread(firebase.init)  # connects Firestore/Auth/Storage/FCM and loads the data mirror
    await hub.start()
    tasks = []
    if s.run_background_tasks and not s.serverless:
        if s.data_source == "demo":
            tasks.append(asyncio.create_task(_loop("simulator", simulator.tick, s.simulator_tick_seconds)))
        if s.data_source == "provider":
            tasks.append(asyncio.create_task(_loop("provider", gps_provider.poll, 5)))
        tasks.append(asyncio.create_task(_loop("bus-monitor", monitor.check_buses, 15)))
        tasks.append(asyncio.create_task(_loop("delays", monitor.check_delays, 30)))
        tasks.append(asyncio.create_task(_loop("watches", monitor.check_watches, 15)))
        tasks.append(asyncio.create_task(_loop("retention", monitor.purge_old_locations, 3600)))
    log.info("Speedo Live API started (data source: %s)", s.data_source)
    yield
    for t in tasks:
        t.cancel()
    try:
        await asyncio.to_thread(store.commit, True)  # save the latest live positions before exiting
    except Exception:
        log.exception("final Firestore write failed")
    await hub.stop()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Speedo Live: bus tracking and route navigation for Lahore.\n\n"
        "Data is stored in Cloud Firestore; accounts are Firebase Authentication users.\n\n"
        "Authenticate with `POST /api/auth/login` and send the returned Firebase ID token as "
        "`Authorization: Bearer <token>`; renew it with `POST /api/auth/refresh`.\n"
        "Live positions stream over the `/ws/live` WebSocket.\n\n"
        "In DEMO mode, buses flagged is_demo are moved by a simulator."
    ),
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials="*" not in origins,
                   allow_methods=["*"], allow_headers=["*"])


if settings.serverless:
    @app.middleware("http")
    async def serverless_background(request: Request, call_next):
        """Serverless: connect on first use and let API calls drive the simulator and monitors."""
        if not store.ready:
            try:
                await asyncio.to_thread(firebase.init)
            except Exception as exc:  # explain the problem instead of crashing the function
                log.exception("Firebase setup failed")
                return JSONResponse(status_code=503, content={
                    "detail": f"Server setup problem: {type(exc).__name__}: {exc}"[:500],
                    "hint": "Check FIREBASE_PROJECT_ID, FIREBASE_WEB_API_KEY and FIREBASE_CREDENTIALS_JSON in the hosting settings."})
        if request.url.path.startswith("/api/") and settings.run_background_tasks:
            await asyncio.to_thread(on_request.catch_up)
        return await call_next(request)


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health", tags=["system"])
def health():
    db_ok = redis_ok = False
    try:
        db_ok = bool(store.backend and store.backend.ping())
    except Exception:
        log.exception("Firestore health check failed")
    try:
        redis_ok = bool(hub.redis_sync and hub.redis_sync.ping())
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "database": "firestore", "firestore": db_ok,
            "firebase_project": settings.firebase_project_id, "auth": firebase.auth_provider is not None,
            "storage": firebase.files.enabled, "redis": redis_ok, "data_source": settings.data_source}


for r in (auth.router, public.router, me.router, driver.router, admin.router, complaints.router, ws.router):
    app.include_router(r)

# Optional: serve the exported web app (web/out) from the same container.
if settings.web_dist:
    import os

    from fastapi.staticfiles import StaticFiles

    if os.path.isdir(settings.web_dist):
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    else:
        log.warning("WEB_DIST %s not found; web app not served", settings.web_dist)
