"""Password hashing (scrypt), JWT tokens, token revocation and rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
import uuid
from collections import deque

import jwt

from .cache import cache
from .config import settings

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, role: str, *, typ: str = "access", ttl_s: int | None = None, extra: dict | None = None) -> str:
    now = int(time.time())
    ttl = ttl_s if ttl_s is not None else settings.jwt_ttl_minutes * 60
    payload = {"sub": str(user_id), "role": role, "typ": typ, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, typ: str = "access") -> dict | None:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "jti"]})
    except jwt.PyJWTError:
        return None
    if data.get("typ") != typ:
        return None
    if cache.get(f"revoked:{data['jti']}"):
        return None
    return data


def revoke_token(claims: dict) -> None:
    ttl = max(1, int(claims["exp"] - time.time()))
    cache.set(f"revoked:{claims['jti']}", "1", ttl=ttl)


class RateLimiter:
    """Sliding-window limiter keyed by (bucket, client)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_s - (now - q[0])) + 1
                return False, retry
            q.append(now)
            if len(self._hits) > 50_000:  # crude memory guard
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < window_s}
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
