import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal, engine
from .limits import limiter
from .routers import admin, auth, driver, me, public, ws
from .services import gps_provider, monitor, simulator
from .services.realtime import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("speedo")


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
    if s.environment == "production" and s.jwt_secret.startswith("dev-only"):
        raise RuntimeError("Set JWT_SECRET to a long random value before running in production")
    await hub.start()
    tasks = []
    if s.run_background_tasks:
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
    await hub.stop()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Speedo Live: bus tracking and route navigation for Lahore.\n\n"
        "Authenticate with `POST /api/auth/login` and send `Authorization: Bearer <token>`.\n"
        "Live positions stream over the `/ws/live` WebSocket.\n\n"
        "In DEMO mode all buses, routes and schedules are simulated sample data."
    ),
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials="*" not in origins,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health", tags=["system"])
def health():
    db_ok = redis_ok = False
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        redis_ok = bool(hub.redis_sync and hub.redis_sync.ping())
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "redis": redis_ok,
            "data_source": settings.data_source}


for r in (auth.router, public.router, me.router, driver.router, admin.router, ws.router):
    app.include_router(r)

# Optional: serve the exported web app (web/out) from the same container.
if settings.web_dist:
    import os

    from fastapi.staticfiles import StaticFiles

    if os.path.isdir(settings.web_dist):
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    else:
        log.warning("WEB_DIST %s not found; web app not served", settings.web_dist)
