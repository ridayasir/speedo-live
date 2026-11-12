"""Notifications: in-app inbox + Firebase Cloud Messaging (HTTP v1) push.

Without FCM credentials notifications are still stored and shown in the in-app
inbox; push delivery is skipped and reported as `pushed = false`.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

import jwt

from ..config import settings
from ..db import get_db, iso, utcnow
from .network import network

log = logging.getLogger("speedo.notify")

PREF_FOR_KIND = {"approaching": "approaching", "arriving": "approaching", "delay": "delays",
                 "disruption": "disruptions", "schedule_change": "schedule_changes"}


class FCMClient:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self) -> None:
        self._token: str | None = None
        self._exp = 0.0
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._exp - 60:
                return self._token
            with open(settings.fcm_service_account_file, encoding="utf-8") as fh:
                sa = json.load(fh)
            now = int(time.time())
            assertion = jwt.encode(
                {"iss": sa["client_email"], "scope": self.SCOPE, "aud": self.TOKEN_URL, "iat": now, "exp": now + 3600},
                sa["private_key"], algorithm="RS256",
            )
            body = f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion={assertion}".encode()
            req = urllib.request.Request(self.TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
            self._token, self._exp = data["access_token"], time.time() + data.get("expires_in", 3600)
            return self._token

    def send(self, token: str, title: str, body: str, data: dict) -> str:
        """Returns 'ok', 'invalid_token' or 'error'."""
        url = f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send"
        msg = {"message": {"token": token, "notification": {"title": title, "body": body},
                           "data": {k: str(v) for k, v in data.items()},
                           "android": {"priority": "high", "notification": {"channel_id": "bus-alerts"}}}}
        req = urllib.request.Request(url, data=json.dumps(msg).encode(), method="POST", headers={
            "Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10):
                return "ok"
        except urllib.error.HTTPError as e:
            if e.code in (400, 404) and b"UNREGISTERED" in e.read():
                return "invalid_token"
            log.warning("FCM send failed: HTTP %s", e.code)
            return "error"
        except Exception as e:  # network errors
            log.warning("FCM send failed: %s", e)
            return "error"


fcm = FCMClient()


def get_prefs(user_id: int) -> dict:
    db = get_db()
    row = db.one("SELECT * FROM notification_prefs WHERE user_id = ?", (user_id,))
    if not row:
        db.execute("INSERT INTO notification_prefs (user_id) VALUES (?)", (user_id,))
        row = db.one("SELECT * FROM notification_prefs WHERE user_id = ?", (user_id,))
    return {k: (bool(v) if k not in ("user_id", "approaching_lead_min") else v) for k, v in row.items()}


def _push(notification_id: int, user_id: int, title: str, body: str, data: dict) -> None:
    db = get_db()
    tokens = db.all("SELECT id, token FROM device_tokens WHERE user_id = ?", (user_id,))
    sent = False
    for t in tokens:
        res = fcm.send(t["token"], title, body, {**data, "notification_id": notification_id})
        if res == "ok":
            sent = True
        elif res == "invalid_token":
            db.execute("DELETE FROM device_tokens WHERE id = ?", (t["id"],))
    if sent:
        db.execute("UPDATE notifications SET pushed = ? WHERE id = ?", (True, notification_id))


def notify(user_id: int, kind: str, title: str, body: str, data: dict | None = None, dedupe_key: str | None = None) -> int | None:
    """Store a notification (once per dedupe_key) and push it if FCM is configured
    and the user's preferences allow this kind."""
    pref = PREF_FOR_KIND.get(kind)
    if pref and not get_prefs(user_id).get(pref, True):
        return None
    db = get_db()
    if dedupe_key and db.one("SELECT id FROM notifications WHERE user_id = ? AND dedupe_key = ?", (user_id, dedupe_key)):
        return None
    nid = db.insert("notifications", {
        "user_id": user_id, "kind": kind, "title": title, "body": body, "data_json": json.dumps(data or {}),
        "dedupe_key": dedupe_key, "pushed": False, "created_at": iso(),
    })
    if settings.fcm_configured:
        threading.Thread(target=_push, args=(nid, user_id, title, body, data or {}), daemon=True).start()
    return nid


def notify_route_followers(route_id: int | None, stop_id: int | None, kind: str, title: str, body: str, dedupe_key: str) -> int:
    db = get_db()
    users: set[int] = set()
    if route_id:
        users |= {r["user_id"] for r in db.all("SELECT user_id FROM favorite_routes WHERE route_id = ?", (route_id,))}
    if stop_id:
        users |= {r["user_id"] for r in db.all("SELECT user_id FROM favorite_stops WHERE stop_id = ?", (stop_id,))}
    if not route_id and not stop_id:  # network-wide alert
        users |= {r["user_id"] for r in db.all("SELECT DISTINCT user_id FROM favorite_routes")}
    n = 0
    for uid in users:
        if notify(uid, kind, title, body, {"route_id": route_id or "", "stop_id": stop_id or ""}, dedupe_key):
            n += 1
    return n


def watch_sweep() -> int:
    """Notify users whose watched bus is approaching their stop."""
    from .eta import arrivals_at_stop

    db = get_db()
    now = iso()
    db.execute("DELETE FROM stop_watches WHERE expires_at < ?", (now,))
    sent = 0
    for w in db.all("SELECT * FROM stop_watches"):
        arr = arrivals_at_stop(w["stop_id"], w["route_id"])
        stop = db.one("SELECT name FROM stops WHERE id = ?", (w["stop_id"],))
        for a in arr["live"]:
            if w["bus_id"] and a["bus_id"] != w["bus_id"]:
                continue
            mins = a["eta_s"] / 60
            demo = ""
            if mins <= 1.0:
                kind, title = "arriving", f"Bus {a['bus_number']} is arriving{demo}"
                body = f"Route {a['route_code']} is about to reach {stop['name']}."
                key = f"watch:{w['id']}:arriving:{a['bus_id']}:{a['eta_at'][:13]}"
            elif mins <= w["lead_min"]:
                kind, title = "approaching", f"Bus {a['bus_number']} arrives in about {round(mins)} min{demo}"
                body = f"Route {a['route_code']} towards {a['towards']} is approaching {stop['name']}."
                key = f"watch:{w['id']}:approach:{a['bus_id']}:{a['eta_at'][:13]}"
            else:
                continue
            if notify(w["user_id"], kind, title, body, {"bus_id": a["bus_id"], "stop_id": w["stop_id"]}, key):
                sent += 1
    return sent


def delay_sweep() -> int:
    """One delay notification per delayed trip for users following the route."""
    from .tracking import compute_status

    db = get_db()
    sent = 0
    for t in db.all("SELECT * FROM trips WHERE status = 'active'"):
        bus = db.one("SELECT * FROM buses WHERE id = ?", (t["bus_id"],))
        route = network.get(t["route_id"])
        status, delay = compute_status(bus, t, route)
        if status == "delayed":
            demo = ""
            sent += notify_route_followers(
                t["route_id"], None, "delay", f"Route {route.code} bus {bus['bus_number']} is delayed{demo}",
                f"Running about {round(delay)} min behind schedule.", f"delay:trip:{t['id']}")
    return sent
