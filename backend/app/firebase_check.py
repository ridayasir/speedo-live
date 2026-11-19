"""Verify the Firebase connection end to end, against the real project in backend/.env.

    cd backend
    .venv\\Scripts\\python -m app.firebase_check          (Windows)
    python -m app.firebase_check                         (macOS / Linux)

Checks, cleaning up after itself:
  1. credentials load and the Admin SDK initialises
  2. Firestore: write, read back and delete a document; the id counter works
  3. Authentication: create a temporary user, sign in with the Web API key, verify the ID token,
     refresh it, then delete the user (needs the Email/Password sign-in provider enabled)
  4. Storage (only if FIREBASE_STORAGE_BUCKET is set): upload, read back and delete a small file
  5. Cloud Messaging: a dry-run send, which checks the service account may use FCM
Exit code 0 means every check passed.
"""
from __future__ import annotations

import secrets
import sys
import traceback
from datetime import datetime, timezone

from .config import get_settings

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        try:
            detail = fn() or ""
            results.append((name, True, detail))
            print(f"  PASS  {name}  {detail}")
        except Exception as exc:  # report every failure, then keep going
            results.append((name, False, str(exc)))
            print(f"  FAIL  {name}  {type(exc).__name__}: {exc}")
            if "-v" in sys.argv:
                traceback.print_exc()
        return fn
    return deco


def main() -> int:
    s = get_settings()
    print(f"Firebase project: {s.firebase_project_id or '(FIREBASE_PROJECT_ID not set)'}")
    from . import firebase
    from .store import store

    @check("Admin SDK + Firestore connection (loads the data mirror)")
    def _init():
        firebase.init()
        counts = ", ".join(f"{m.__collection__}={len(v)}" for m, v in store.cache.items() if v)
        return f"[{counts or 'empty project'}]"

    if not store.ready:
        print("\nCannot continue without a Firestore connection. Check FIREBASE_* in backend/.env.")
        return 1
    db = store.backend.db

    @check("Firestore write / read / delete")
    def _fs():
        ref = db.collection("_meta").document(f"check-{secrets.token_hex(4)}")
        stamp = datetime.now(timezone.utc)
        ref.set({"at": stamp, "path": [{"lat": 31.5, "lng": 74.3}]})
        got = ref.get().to_dict()
        ref.delete()
        assert got and got["path"][0]["lat"] == 31.5, got
        return "ok"

    @check("Firestore id counter (transaction)")
    def _ctr():
        a = store.backend.allocate("_check", 1)
        b = store.backend.allocate("_check", 1)
        db.collection("_counters").document("_check").delete()
        assert b == a + 1, (a, b)
        return "ok"

    @check("Authentication: create user, sign in, verify, refresh, delete")
    def _auth():
        auth = firebase.auth_provider
        email = f"speedo-check-{secrets.token_hex(4)}@example.com"
        pw = secrets.token_urlsafe(12)
        uid = auth.create_user(email, pw, "Speedo connection check")
        try:
            t = auth.sign_in(email, pw)
            assert auth.verify(t.id_token) == uid, "ID token did not verify"
            t2 = auth.refresh(t.refresh_token)
            assert auth.verify(t2.id_token) == uid, "refreshed token did not verify"
        finally:
            auth.delete_user(uid)
        return "ok"

    if firebase.files.enabled:
        @check(f"Storage upload / read / delete ({s.firebase_storage_bucket})")
        def _storage():
            from firebase_admin import storage

            path = f"_check/{secrets.token_hex(4)}.txt"
            firebase.files.upload(path, b"speedo", "text/plain")
            blob = storage.bucket(s.firebase_storage_bucket).blob(path)
            assert blob.download_as_bytes() == b"speedo"
            blob.delete()
            return "ok"
    else:
        print("  SKIP  Storage (FIREBASE_STORAGE_BUCKET not set; imported files are then not archived)")

    @check("Cloud Messaging (dry run)")
    def _fcm():
        from firebase_admin import messaging

        msg = messaging.Message(topic="speedo-connection-check",
                                notification=messaging.Notification(title="check", body="check"))
        return f"message id {messaging.send(msg, dry_run=True)}"

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print("Fix the failures above (see README section 1, 'Firebase setup').")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
