"""Database sessions. The database is Cloud Firestore (see app/store.py and app/firebase.py)."""
from collections.abc import Iterator

from .store import Session


def SessionLocal() -> Session:  # noqa: N802 - kept for the existing call sites
    return Session()


def get_db() -> Iterator[Session]:
    db = Session()
    try:
        yield db
    finally:
        db.close()
