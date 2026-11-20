"""In-memory stand-ins for Firestore, Firebase Authentication and Storage, used by the test suite.

They follow the real services' rules that matter to the app: Firestore rejects nested arrays and
unsupported value types, data is copied on write/read (no shared references), and Firebase Auth
returns the same error codes as the Identity Toolkit REST API.
"""
from __future__ import annotations

import copy
import itertools
import secrets
from datetime import datetime

from app.firebase import FirebaseError, Tokens
from app.store import _match

_ALLOWED = (type(None), bool, int, float, str, datetime)


def _check(value, path="", in_array=False):
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"Firestore map keys must be strings at {path}")
            _check(v, f"{path}.{k}", False)
    elif isinstance(value, list):
        if in_array:
            raise TypeError(f"Firestore does not support nested arrays ({path})")
        for i, v in enumerate(value):
            _check(v, f"{path}[{i}]", True)
    elif not isinstance(value, _ALLOWED):
        raise TypeError(f"Firestore cannot store {type(value).__name__} at {path}")


class _Row:
    def __init__(self, data):
        self.__dict__.update(data)

    def __getattr__(self, k):
        return None


class FakeFirestore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {}
        self.writes = 0

    def stream(self, coll, filters, order_by=None, desc=False, limit=None):
        rows = [(i, copy.deepcopy(d)) for i, d in self.data.get(coll, {}).items()
                if _match(_Row(d), filters)]
        if order_by:
            rows.sort(key=lambda r: (r[1].get(order_by) is None, r[1].get(order_by) or 0), reverse=desc)
        return rows[:limit] if limit else rows

    def get(self, coll, doc_id):
        d = self.data.get(coll, {}).get(doc_id)
        return copy.deepcopy(d) if d is not None else None

    def write(self, sets, deletes):
        for c, i, d in sets:
            _check(d, f"{c}/{i}")
        for c, i, d in sets:
            self.data.setdefault(c, {})[i] = copy.deepcopy(d)
            self.writes += 1
        for c, i in deletes:
            self.data.get(c, {}).pop(i, None)
            self.writes += 1

    def allocate(self, name, n):
        cur = self.data.setdefault("_counters", {}).setdefault(name, {"value": 0})
        cur["value"] += n
        return cur["value"]

    def ping(self):
        return True


class FakeAuth:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.id_tokens: dict[str, str] = {}
        self.refresh_tokens: dict[str, str] = {}
        self._n = itertools.count(1)

    def create_user(self, email, password, display_name=None):
        if any(u["email"] == email for u in self.users.values()):
            raise FirebaseError("EMAIL_EXISTS", 409, "An account with this email or phone already exists")
        if len(password) < 6:
            raise FirebaseError("WEAK_PASSWORD", 422, "Password should be at least 6 characters")
        uid = f"uid{next(self._n)}"
        self.users[uid] = {"email": email, "password": password, "disabled": False, "display_name": display_name}
        return uid

    def _issue(self, uid):
        t, r = "id." + secrets.token_hex(8), "rt." + secrets.token_hex(8)
        self.id_tokens[t] = uid
        self.refresh_tokens[r] = uid
        return Tokens(t, r, 3600, uid)

    def sign_in(self, email, password):
        u = next(((uid, u) for uid, u in self.users.items() if u["email"] == email), None)
        if not u or u[1]["password"] != password:
            raise FirebaseError("INVALID_LOGIN_CREDENTIALS", 401, "Incorrect email/phone or password")
        if u[1]["disabled"]:
            raise FirebaseError("USER_DISABLED", 403, "This account is deactivated")
        return self._issue(u[0])

    def refresh(self, refresh_token):
        uid = self.refresh_tokens.get(refresh_token)
        if not uid:
            raise FirebaseError("INVALID_REFRESH_TOKEN", 401, "Incorrect email/phone or password")
        if self.users[uid]["disabled"]:
            raise FirebaseError("USER_DISABLED", 403, "This account is deactivated")
        return self._issue(uid)

    def verify(self, token):
        uid = self.id_tokens.get(token)
        return uid if uid and not self.users[uid]["disabled"] else None

    def set_password(self, uid, password):
        self.users[uid]["password"] = password

    def set_disabled(self, uid, disabled):
        self.users[uid]["disabled"] = disabled

    def set_display_name(self, uid, name):
        self.users[uid]["display_name"] = name

    def set_email(self, uid, email):
        if any(u["email"] == email for k, u in self.users.items() if k != uid):
            raise FirebaseError("EMAIL_EXISTS", 409, "An account with this email already exists")
        self.users[uid]["email"] = email

    def delete_user(self, uid):
        self.users.pop(uid, None)

    def find_uid_by_email(self, email):
        return next((uid for uid, u in self.users.items() if u["email"] == email), None)


class FakeFiles:
    enabled = True

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def upload(self, path, data, content_type=None):
        self.blobs[path] = data
        return f"gs://test-bucket/{path}"


class FakePush:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def send(self, token, title, body, data):
        self.sent.append((token, title, body, data))
        return True
