"""Notifications: stored in the database and pushed through Firebase Cloud Messaging when configured.

FCM needs FCM_PROJECT_ID and FCM_CREDENTIALS_FILE (a service-account JSON). Without them,
notifications are still stored and shown in the app's inbox; delivery_status is "stored".
"""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import DeviceToken, FavoriteRoute, Notification, User
from .tracking import utcnow

log = logging.getLogger("speedo.notify")

PREF_FOR_KIND = {
    "bus_approaching": "bus_approaching",
    "bus_arriving": "bus_approaching",
    "delay": "delays",
    "disruption": "disruptions",
    "schedule_change": "schedule_changes",
}


class FcmSender:
    def __init__(self) -> None:
        s = get_settings()
        self.enabled = bool(s.fcm_project_id and s.fcm_credentials_file)
        self._creds = None
        if self.enabled:
            try:
                from google.oauth2 import service_account

                self._creds = service_account.Credentials.from_service_account_file(
                    s.fcm_credentials_file, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
                )
            except Exception as exc:  # pragma: no cover - depends on credentials
                log.warning("FCM disabled: %s", exc)
                self.enabled = False

    def send(self, token: str, title: str, body: str, data: dict) -> bool:  # pragma: no cover - network
        if not self.enabled:
            return False
        from google.auth.transport.requests import Request

        if not self._creds.valid:
            self._creds.refresh(Request())
        url = f"https://fcm.googleapis.com/v1/projects/{get_settings().fcm_project_id}/messages:send"
        msg = {"message": {"token": token, "notification": {"title": title, "body": body},
                           "data": {k: str(v) for k, v in data.items()}}}
        r = httpx.post(url, json=msg, headers={"Authorization": f"Bearer {self._creds.token}"}, timeout=10)
        return r.status_code == 200


_sender: FcmSender | None = None


def sender() -> FcmSender:
    global _sender
    if _sender is None:
        _sender = FcmSender()
    return _sender


def notify(db: Session, user: User, kind: str, title: str, body: str, data: dict | None = None,
           dedupe_key: str | None = None, dedupe_hours: float = 6) -> Notification | None:
    prefs = user.notification_prefs or {}
    pref = PREF_FOR_KIND.get(kind)
    if pref and prefs.get(pref) is False:
        return None
    if dedupe_key:
        recent = db.execute(
            select(Notification.id).where(
                Notification.user_id == user.id,
                Notification.dedupe_key == dedupe_key,
                Notification.created_at >= utcnow() - timedelta(hours=dedupe_hours),
            )
        ).first()
        if recent:
            return None
    n = Notification(user_id=user.id, kind=kind, title=title, body=body, data=data or {}, dedupe_key=dedupe_key)
    tokens = db.execute(select(DeviceToken).where(DeviceToken.user_id == user.id)).scalars().all()
    delivered = False
    for t in tokens:
        try:
            delivered = sender().send(t.token, title, body, data or {}) or delivered
        except Exception as exc:  # pragma: no cover
            log.warning("FCM send failed: %s", exc)
    n.delivery_status = "pushed" if delivered else "stored"
    db.add(n)
    db.flush()
    return n


def notify_route_followers(db: Session, route_id: int, kind: str, title: str, body: str, dedupe_key: str) -> int:
    users = db.execute(
        select(User).join(FavoriteRoute, FavoriteRoute.user_id == User.id).where(FavoriteRoute.route_id == route_id)
    ).scalars().all()
    count = 0
    for u in users:
        if notify(db, u, kind, title, body, {"route_id": route_id}, dedupe_key=dedupe_key):
            count += 1
    return count
