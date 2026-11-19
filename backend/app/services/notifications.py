"""Notifications: stored in Firestore and pushed to phones through Firebase Cloud Messaging.

Push uses the same Firebase service account as the database. A notification is always kept in the
in-app inbox; delivery_status is "pushed" when at least one of the user's devices accepted it.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from .. import firebase
from ..models import DeviceToken, FavoriteRoute, Notification, User
from ..store import Session
from .tracking import utcnow

log = logging.getLogger("speedo.notify")

PREF_FOR_KIND = {
    "bus_approaching": "bus_approaching",
    "bus_arriving": "bus_approaching",
    "delay": "delays",
    "disruption": "disruptions",
    "schedule_change": "schedule_changes",
}


def _push(db: Session, user: User, title: str, body: str, data: dict) -> bool:
    sender = firebase.push
    if sender is None:
        return False
    delivered = False
    for t in db.where(DeviceToken, user_id=user.id):
        try:
            delivered = sender.send(t.token, title, body, data) or delivered
        except Exception as exc:
            # tokens of uninstalled apps are rejected as "unregistered"; forget them
            if "registration-token-not-registered" in str(exc) or "Requested entity was not found" in str(exc):
                db.delete(t)
            else:
                log.warning("FCM send failed: %s", exc)
    return delivered


def notify(db: Session, user: User, kind: str, title: str, body: str, data: dict | None = None,
           dedupe_key: str | None = None, dedupe_hours: float = 6) -> Notification | None:
    prefs = user.notification_prefs or {}
    pref = PREF_FOR_KIND.get(kind)
    if pref and prefs.get(pref) is False:
        return None
    if dedupe_key:
        since = utcnow() - timedelta(hours=dedupe_hours)
        recent = db.where(Notification, ("created_at", ">=", since), user_id=user.id, dedupe_key=dedupe_key)
        if recent:
            return None
    n = Notification(user_id=user.id, kind=kind, title=title, body=body, data=data or {}, dedupe_key=dedupe_key)
    n.delivery_status = "pushed" if _push(db, user, title, body, data or {}) else "stored"
    db.add(n)
    return n


def notify_route_followers(db: Session, route_id: int, kind: str, title: str, body: str, dedupe_key: str) -> int:
    count = 0
    for fav in db.where(FavoriteRoute, route_id=route_id):
        u = db.get(User, fav.user_id)
        if u and notify(db, u, kind, title, body, {"route_id": route_id}, dedupe_key=dedupe_key):
            count += 1
    return count
