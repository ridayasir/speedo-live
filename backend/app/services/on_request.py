"""Background work for serverless hosting (Vercel), where no loop can run between requests.

Instead, API requests advance the world by the time that has passed:
- the bus simulator moves buses by the elapsed time in steps of at most 10 s (so dwell at stops still works);
  after a long idle gap the simulator restarts from where the buses are, with schedules realigned;
- the monitor (stale GPS, arrival alerts, delays) runs at most once a minute.
Each serverless instance keeps its own pace; a lock makes concurrent requests in one instance take turns.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from ..config import get_settings
from ..db import SessionLocal
from . import monitor, simulator
from .tracking import utcnow

log = logging.getLogger("speedo.on_request")
_lock = threading.Lock()
_last_tick: float | None = None
_last_wall = None  # wall-clock time of the last simulated fix
_last_monitor = 0.0
STEP_SECONDS = 10.0
MAX_CATCH_UP = 300.0  # longer gaps restart the simulation instead of replaying them


def catch_up() -> None:
    """Run the simulator and monitors for the time since the previous call (non-blocking if busy)."""
    global _last_tick, _last_wall, _last_monitor
    if not _lock.acquire(blocking=False):
        return  # another request in this instance is already doing it
    try:
        s = get_settings()
        now = time.monotonic()
        with SessionLocal() as db:
            if s.data_source == "demo":
                if _last_tick is None or _last_wall is None or now - _last_tick > MAX_CATCH_UP:
                    simulator.reset()  # resume from the saved positions, schedules realigned
                    _last_wall = utcnow()
                    simulator.tick(db, dt=s.simulator_tick_seconds, at=_last_wall)
                    _last_tick = now
                elif now - _last_tick >= s.simulator_tick_seconds:
                    left = now - _last_tick
                    while left >= 2:  # each replayed step gets its own time (GPS drops fixes < 2 s apart)
                        step = min(STEP_SECONDS, left)
                        _last_wall += timedelta(seconds=step)
                        simulator.tick(db, dt=step, at=_last_wall)
                        left -= step
                    _last_tick = now - left
            if now - _last_monitor >= 60:
                _last_monitor = now
                monitor.check_buses(db)
                monitor.check_delays(db)
                monitor.check_watches(db)
    except Exception:
        log.exception("on-request background work failed")
    finally:
        _lock.release()
