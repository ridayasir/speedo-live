"""Serverless hosting (Vercel): requests drive the simulator; the entry point restores rewritten paths."""
import asyncio
import importlib.util
import os

from app.models import Bus
from app.services import on_request


def test_catch_up_moves_buses_by_elapsed_time(db, monkeypatch):
    before = {b.bus_number: b.last_gps_at for b in db.all(Bus) if b.is_demo}
    clock = [1000.0]
    monkeypatch.setattr(on_request.time, "monotonic", lambda: clock[0])
    on_request._last_tick = None
    on_request.catch_up()  # first request: (re)start
    first = {b.bus_number: (b.last_lat, b.last_lng) for b in db.all(Bus) if b.is_demo}
    clock[0] += 25  # 25 s later: replayed in 10 s steps
    on_request.catch_up()
    after = {b.bus_number: (b.last_lat, b.last_lng) for b in db.all(Bus) if b.is_demo}
    assert any(after[k] != first[k] for k in after)
    assert any(b.last_gps_at != before.get(b.bus_number) for b in db.all(Bus) if b.is_demo)
    clock[0] += 1  # too soon for another tick: nothing happens
    on_request.catch_up()
    assert {b.bus_number: (b.last_lat, b.last_lng) for b in db.all(Bus) if b.is_demo} == after


def test_vercel_entry_restores_the_original_path(client):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    spec = importlib.util.spec_from_file_location("vercel_entry", os.path.join(root, "api", "index.py"))
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    seen = {}

    async def fake_app(scope, receive, send):
        seen.update(path=scope["path"], qs=scope["query_string"])

    entry.speedo = fake_app
    scope = {"type": "http", "path": "/api/index", "raw_path": b"/api/index", "query_string": b"__p=%2Fapi%2Fstops&limit=5"}
    asyncio.run(entry.app(scope, None, None))
    assert seen == {"path": "/api/stops", "qs": b"limit=5"}
