"""Key/value cache with TTL: Redis when REDIS_URL is set, in-process memory otherwise.

Used for latest bus positions and revoked tokens. Redis is spoken directly over
RESP so no extra client package is required.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from urllib.parse import urlparse

from .config import settings

log = logging.getLogger("speedo.cache")


class MemoryCache:
    backend = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            value, exp = item
            if exp is not None and exp < time.monotonic():
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + ttl if ttl else None)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def ping(self) -> bool:
        return True


class RedisCache:
    """Minimal synchronous Redis client (GET/SET/DEL/PING) over RESP2."""

    backend = "redis"

    def __init__(self, url: str) -> None:
        u = urlparse(url)
        self.host, self.port = u.hostname or "localhost", u.port or 6379
        self.password = u.password
        self.db = int((u.path or "/0").lstrip("/") or 0)
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._buf = b""

    def _connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=3)
        self._buf = b""
        if self.password:
            self._cmd_raw("AUTH", self.password)
        if self.db:
            self._cmd_raw("SELECT", str(self.db))

    def _readline(self) -> bytes:
        while b"\r\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("redis closed connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r\n", 1)
        return line

    def _read(self):
        line = self._readline()
        kind, rest = line[:1], line[1:]
        if kind == b"+":
            return rest.decode()
        if kind == b"-":
            raise RuntimeError(rest.decode())
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            if n < 0:
                return None
            while len(self._buf) < n + 2:
                self._buf += self._sock.recv(65536)
            data, self._buf = self._buf[:n], self._buf[n + 2 :]
            return data.decode()
        if kind == b"*":
            return [self._read() for _ in range(int(rest))]
        raise RuntimeError(f"unexpected redis reply {line!r}")

    def _cmd_raw(self, *args: str):
        payload = f"*{len(args)}\r\n".encode() + b"".join(
            f"${len(a.encode())}\r\n".encode() + a.encode() + b"\r\n" for a in args
        )
        self._sock.sendall(payload)
        return self._read()

    def _cmd(self, *args: str):
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._sock is None:
                        self._connect()
                    return self._cmd_raw(*args)
                except (OSError, ConnectionError):
                    self._sock = None
                    if attempt == 2:
                        raise

    def get(self, key: str) -> str | None:
        return self._cmd("GET", key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl:
            self._cmd("SET", key, value, "EX", str(int(ttl)))
        else:
            self._cmd("SET", key, value)

    def delete(self, key: str) -> None:
        self._cmd("DEL", key)

    def ping(self) -> bool:
        try:
            return self._cmd("PING") == "PONG"
        except Exception:
            return False


def _make_cache():
    if settings.redis_url:
        c = RedisCache(settings.redis_url)
        if c.ping():
            log.info("using Redis cache at %s:%s", c.host, c.port)
            return c
        log.warning("REDIS_URL set but Redis is unreachable; falling back to in-memory cache")
    return MemoryCache()


cache = _make_cache()
