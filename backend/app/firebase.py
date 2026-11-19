"""Firebase connection: Cloud Firestore (database), Authentication (accounts), Storage (files) and
Cloud Messaging (push), all through the Firebase Admin SDK with one service account.

Configuration (environment variables, see backend/.env.example):
    FIREBASE_PROJECT_ID          the Firebase project id
    FIREBASE_CREDENTIALS_FILE    path to the service-account JSON  (or FIREBASE_CREDENTIALS_JSON with its content;
                                 on Google Cloud, Application Default Credentials are used when both are empty)
    FIREBASE_WEB_API_KEY         the project's Web API key (Project settings > General); used to sign users in
    FIREBASE_STORAGE_BUCKET      e.g. my-project.firebasestorage.app (optional: keeps a copy of imported files)

The Firebase emulators are used automatically when FIRESTORE_EMULATOR_HOST / FIREBASE_AUTH_EMULATOR_HOST are set.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

from .config import get_settings
from .store import store

log = logging.getLogger("speedo.firebase")


class FirebaseError(Exception):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


@dataclass
class Tokens:
    id_token: str
    refresh_token: str
    expires_in: int
    uid: str


# ----------------------------------------------------------------------------- Firestore
class FirestoreBackend:
    """Thin adapter used by app.store. Only single-field filters are sent to Firestore (no composite indexes)."""

    def __init__(self, client) -> None:
        self.db = client

    def stream(self, coll: str, filters: list, order_by: str | None = None, desc: bool = False,
               limit: int | None = None) -> list[tuple[str, dict]]:
        from google.cloud.firestore_v1.base_query import FieldFilter
        from google.cloud.firestore_v1.query import Query

        q = self.db.collection(coll)
        eq = [f for f in filters if f[1] in ("==", "in")]
        rng = [f for f in filters if f[1] in ("<", "<=", ">", ">=")]
        rng_fields = {f[0] for f in rng}
        direction = Query.DESCENDING if desc else Query.ASCENDING
        if eq:
            for field, op, value in eq:
                q = q.where(filter=FieldFilter(field, op, value))
        elif len(rng_fields) == 1:
            for field, op, value in rng:
                q = q.where(filter=FieldFilter(field, op, value))
            if order_by in rng_fields:
                q = q.order_by(order_by, direction=direction)
                if limit:
                    q = q.limit(limit)
        elif not rng and order_by:
            q = q.order_by(order_by, direction=direction)
            if limit:
                q = q.limit(limit)
        return [(d.id, d.to_dict()) for d in q.stream()]

    def get(self, coll: str, doc_id: str) -> dict | None:
        snap = self.db.collection(coll).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def write(self, sets: list[tuple[str, str, dict]], deletes: list[tuple[str, str]]) -> None:
        ops = [("set", c, i, d) for c, i, d in sets] + [("del", c, i, None) for c, i in deletes]
        for start in range(0, len(ops), 450):  # Firestore batches hold at most 500 writes
            batch = self.db.batch()
            for kind, c, i, d in ops[start:start + 450]:
                ref = self.db.collection(c).document(i)
                batch.set(ref, d) if kind == "set" else batch.delete(ref)
            batch.commit()

    def allocate(self, name: str, n: int) -> int:
        """Reserve n ids from a counter document; returns the highest reserved id."""
        from google.cloud import firestore

        ref = self.db.collection("_counters").document(name)

        @firestore.transactional
        def bump(txn):
            snap = ref.get(transaction=txn)
            cur = (snap.to_dict() or {}).get("value", 0) if snap.exists else 0
            txn.set(ref, {"value": cur + n})
            return cur + n

        return bump(self.db.transaction())

    def ping(self) -> bool:
        self.db.collection("_meta").document("health").get()
        return True


# ----------------------------------------------------------------------------- Authentication
class FirebaseAuth:
    """Accounts live in Firebase Authentication (email + password). The API signs users in through the
    Identity Toolkit REST API and verifies Firebase ID tokens with the Admin SDK."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        emu = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
        self.idt = f"http://{emu}/identitytoolkit.googleapis.com/v1" if emu else "https://identitytoolkit.googleapis.com/v1"
        self.sts = f"http://{emu}/securetoken.googleapis.com/v1" if emu else "https://securetoken.googleapis.com/v1"

    @staticmethod
    def _admin():
        from firebase_admin import auth

        return auth

    def create_user(self, email: str, password: str, display_name: str | None = None) -> str:
        auth = self._admin()
        try:
            return auth.create_user(email=email, password=password, display_name=display_name).uid
        except auth.EmailAlreadyExistsError as exc:
            raise FirebaseError("EMAIL_EXISTS", 409, "An account with this email or phone already exists") from exc
        except ValueError as exc:
            raise FirebaseError("INVALID", 422, str(exc)) from exc

    def _rest(self, url: str, body: dict) -> dict:
        if not self.api_key:
            raise FirebaseError("NO_API_KEY", 503, "FIREBASE_WEB_API_KEY is not configured")
        try:
            r = httpx.post(url, params={"key": self.api_key}, json=body, timeout=15)
        except httpx.HTTPError as exc:
            raise FirebaseError("NETWORK", 503, "Cannot reach Firebase Authentication") from exc
        data = r.json() if r.content else {}
        if r.status_code != 200:
            msg = str((data.get("error") or {}).get("message", r.status_code))
            code = msg.split(" ")[0].split(":")[0]
            if code in ("INVALID_LOGIN_CREDENTIALS", "INVALID_PASSWORD", "EMAIL_NOT_FOUND", "INVALID_EMAIL",
                        "INVALID_REFRESH_TOKEN", "TOKEN_EXPIRED", "USER_NOT_FOUND", "MISSING_PASSWORD"):
                raise FirebaseError(code, 401, "Incorrect email/phone or password")
            if code == "USER_DISABLED":
                raise FirebaseError(code, 403, "This account is deactivated")
            if code.startswith("TOO_MANY_ATTEMPTS"):
                raise FirebaseError(code, 429, "Too many attempts. Try again later.")
            log.error("Firebase Auth error: %s", msg)
            raise FirebaseError(code, 503, f"Firebase Authentication error: {msg}")
        return data

    def sign_in(self, email: str, password: str) -> Tokens:
        d = self._rest(f"{self.idt}/accounts:signInWithPassword",
                       {"email": email, "password": password, "returnSecureToken": True})
        return Tokens(d["idToken"], d["refreshToken"], int(d.get("expiresIn", 3600)), d["localId"])

    def refresh(self, refresh_token: str) -> Tokens:
        d = self._rest(f"{self.sts}/token", {"grant_type": "refresh_token", "refresh_token": refresh_token})
        return Tokens(d["id_token"], d["refresh_token"], int(d.get("expires_in", 3600)), d["user_id"])

    def verify(self, id_token: str) -> str | None:
        try:
            return self._admin().verify_id_token(id_token)["uid"]
        except Exception:  # invalid, expired, revoked or malformed
            return None

    def set_password(self, uid: str, password: str) -> None:
        self._admin().update_user(uid, password=password)

    def set_disabled(self, uid: str, disabled: bool) -> None:
        self._admin().update_user(uid, disabled=disabled)

    def set_display_name(self, uid: str, name: str) -> None:
        self._admin().update_user(uid, display_name=name)

    def delete_user(self, uid: str) -> None:
        try:
            self._admin().delete_user(uid)
        except Exception:
            log.warning("could not delete Firebase user %s", uid)

    def find_uid_by_email(self, email: str) -> str | None:
        auth = self._admin()
        try:
            return auth.get_user_by_email(email).uid
        except auth.UserNotFoundError:
            return None


# ----------------------------------------------------------------------------- Storage
class FirebaseFiles:
    def __init__(self, bucket: str | None) -> None:
        self.bucket_name = bucket

    @property
    def enabled(self) -> bool:
        return bool(self.bucket_name)

    def upload(self, path: str, data: bytes, content_type: str | None = None) -> str | None:
        """Store a file; returns its gs:// path, or None when Storage is not configured."""
        if not self.enabled:
            return None
        from firebase_admin import storage

        blob = storage.bucket(self.bucket_name).blob(path)
        blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
        return f"gs://{self.bucket_name}/{path}"


# ----------------------------------------------------------------------------- Cloud Messaging
class FirebasePush:
    enabled = True

    def send(self, token: str, title: str, body: str, data: dict) -> bool:
        from firebase_admin import messaging

        msg = messaging.Message(token=token, notification=messaging.Notification(title=title, body=body),
                                data={k: str(v) for k, v in (data or {}).items()},
                                android=messaging.AndroidConfig(priority="high",
                                                                notification=messaging.AndroidNotification(channel_id="bus-alerts")))
        messaging.send(msg)
        return True


# ----------------------------------------------------------------------------- wiring
auth_provider: FirebaseAuth | None = None
files: FirebaseFiles = FirebaseFiles(None)
push: FirebasePush | None = None
_app = None


def _credentials():
    from firebase_admin import credentials

    s = get_settings()
    if s.firebase_credentials_json:
        return credentials.Certificate(json.loads(s.firebase_credentials_json))
    if s.firebase_credentials_file:
        if not os.path.isfile(s.firebase_credentials_file):
            raise RuntimeError(f"FIREBASE_CREDENTIALS_FILE not found: {s.firebase_credentials_file}")
        return credentials.Certificate(s.firebase_credentials_file)
    return None  # Application Default Credentials (Google Cloud) or emulators


def init() -> None:
    """Connect to Firebase and load the in-memory mirror from Firestore. Safe to call more than once."""
    global auth_provider, files, push, _app
    if store.ready:
        return
    import firebase_admin
    from firebase_admin import firestore

    s = get_settings()
    if not s.firebase_project_id:
        raise RuntimeError("FIREBASE_PROJECT_ID is not set. See backend/.env.example and README section 1.")
    opts = {"projectId": s.firebase_project_id}
    if s.firebase_storage_bucket:
        opts["storageBucket"] = s.firebase_storage_bucket
    _app = firebase_admin.initialize_app(_credentials(), opts) if not firebase_admin._apps else firebase_admin.get_app()
    auth_provider = FirebaseAuth(s.firebase_web_api_key or "")
    files = FirebaseFiles(s.firebase_storage_bucket)
    push = FirebasePush()
    store.connect(FirestoreBackend(firestore.client(_app)))
    log.info("Connected to Firebase project %s", s.firebase_project_id)


def use(backend, auth=None, file_store=None, push_sender=None) -> None:
    """Plug in other implementations (used by the test suite's in-memory fakes)."""
    global auth_provider, files, push
    auth_provider = auth
    files = file_store or FirebaseFiles(None)
    push = push_sender
    store.connect(backend)
