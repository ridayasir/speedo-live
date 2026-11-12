"""Test harness: runs the real ASGI app under uvicorn on a free port with a fresh
SQLite database, in DEMO mode, with background loops disabled (tests drive time)."""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

TMP = tempfile.mkdtemp(prefix="speedo-test-")
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{TMP}/test.db",  # set TEST_DATABASE_URL to run against PostgreSQL
    "SPEEDO_MODE": "demo",
    "SPEEDO_DISABLE_BACKGROUND": "1",
    "JWT_SECRET": "test-secret-test-secret-test-secret-123",
    "AUTH_RATE_LIMIT_PER_MINUTE": "1000",
    "RATE_LIMIT_PER_MINUTE": "100000",
    "SPEEDO_ENV_FILE": "/nonexistent",
    "LOG_LEVEL": "WARNING",
    # small fixed sample network (3 routes, 8 buses) instead of the full imported Speedo network
    "SPEEDO_SEED_FILE": os.path.join(os.path.dirname(__file__), "..", "seed", "demo_network.json"),
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

DEMO_PASSWORD = "Demo@12345"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Client:
    def __init__(self, base: str):
        self.base = base
        self.token: str | None = None

    def request(self, method: str, path: str, body=None, token: str | None = None, raw: bytes | None = None,
                headers: dict | None = None):
        h = {"Accept": "application/json", **(headers or {})}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        tok = token if token is not None else self.token
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read().decode()
                ctype = r.headers.get("content-type", "")
                return r.status, (json.loads(text) if "json" in ctype and text else text)
        except urllib.error.HTTPError as e:
            text = e.read().decode()
            try:
                return e.code, json.loads(text)
            except json.JSONDecodeError:
                return e.code, text

    def get(self, path, **kw): return self.request("GET", path, **kw)
    def post(self, path, body=None, **kw): return self.request("POST", path, body if body is not None else {}, **kw)
    def put(self, path, body, **kw): return self.request("PUT", path, body, **kw)
    def patch(self, path, body, **kw): return self.request("PATCH", path, body, **kw)
    def delete(self, path, **kw): return self.request("DELETE", path, **kw)

    def login(self, identifier: str, password: str = DEMO_PASSWORD) -> str:
        status, data = self.post("/api/auth/login", {"identifier": identifier, "password": password}, token="")
        assert status == 200, data
        return data["token"]


@pytest.fixture(scope="session")
def server():
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    srv = uvicorn.Server(config)
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    deadline = time.time() + 30
    while not srv.started:
        if time.time() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    from app.services.simulator import simulator
    simulator.step(5)  # give simulated DEMO buses a first position
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    th.join(timeout=5)


@pytest.fixture
def client(server):
    return Client(server)


@pytest.fixture(scope="session")
def tokens(server):
    c = Client(server)
    return {"admin": c.login("admin@speedo.demo"), "driver": c.login("driver@speedo.demo"),
            "driver2": c.login("driver2@speedo.demo"), "passenger": c.login("passenger@speedo.demo")}
