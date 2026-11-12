"""Authentication and passenger account endpoints."""
from __future__ import annotations

import datetime as dt
import json

from ..config import settings
from ..db import get_db, iso, utcnow
from ..errors import ApiError, not_found
from ..http import api
from ..schemas import (DeviceTokenIn, FavoriteIn, HistoryIn, LoginIn, PageQ, PrefsIn, ProfileIn, RegisterIn, WatchIn)
from ..security import create_token, hash_password, revoke_token, verify_password
from ..seed import create_user
from ..services.network import network
from ..services.notify import get_prefs

ANY = ("passenger", "driver", "admin")
_DUMMY_HASH = hash_password("timing-equaliser-123")


def _public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"], "phone": u["phone"], "role": u["role"]}


def _session(u: dict) -> dict:
    return {"token": create_token(u["id"], u["role"]), "token_type": "bearer",
            "expires_in": settings.jwt_ttl_minutes * 60, "user": _public_user(u)}


@api.post("/api/auth/register", body=RegisterIn, tags=["auth"], rate=settings.auth_rate_limit_per_min, status=201)
def register(ctx):
    """Create a passenger account (email or Pakistani mobile number)."""
    b = ctx.body
    db = get_db()
    if b.email and db.one("SELECT id FROM users WHERE email = ?", (b.email,)):
        raise ApiError(409, "email_taken", "An account with this email already exists")
    if b.phone and db.one("SELECT id FROM users WHERE phone = ?", (b.phone,)):
        raise ApiError(409, "phone_taken", "An account with this phone number already exists")
    uid = create_user(b.name, b.password, "passenger", email=b.email, phone=b.phone)
    return _session(db.one("SELECT * FROM users WHERE id = ?", (uid,)))


@api.post("/api/auth/login", body=LoginIn, tags=["auth"], rate=settings.auth_rate_limit_per_min)
def login(ctx):
    """Sign in with email or phone number and password. Returns a JWT."""
    ident = ctx.body.identifier.strip().lower()
    db = get_db()
    if "@" in ident:
        u = db.one("SELECT * FROM users WHERE email = ?", (ident,))
    else:
        phone = ident.replace(" ", "").replace("-", "")
        phone = "0" + phone[3:] if phone.startswith("+92") else phone
        u = db.one("SELECT * FROM users WHERE phone = ?", (phone,))
    ok = verify_password(ctx.body.password, u["password_hash"] if u else _DUMMY_HASH)
    if not u or not ok:
        raise ApiError(401, "invalid_credentials", "Email/phone or password is incorrect")
    if not u["is_active"]:
        raise ApiError(403, "account_disabled", "This account has been deactivated")
    if u["role"] == "driver":
        d = db.one("SELECT is_active FROM drivers WHERE user_id = ?", (u["id"],))
        if not d or not d["is_active"]:
            raise ApiError(403, "driver_inactive", "Your driver account is not active. Contact your depot administrator.")
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso(), u["id"]))
    return _session(u)


@api.post("/api/auth/logout", auth=ANY, tags=["auth"])
def logout(ctx):
    """Revoke the current token. A driver's active trip is closed as interrupted."""
    if ctx.user["role"] == "driver":
        from ..services.tracking import active_trip, end_trip
        db = get_db()
        bus = db.one("SELECT b.id FROM buses b JOIN drivers d ON d.id = b.driver_id WHERE d.user_id = ?", (ctx.user_id,))
        trip = active_trip(bus["id"]) if bus else None
        if trip and trip["source"] == "driver":
            end_trip(trip["id"], "interrupted", "driver_logout")
    revoke_token(ctx.claims)
    return {"ok": True}


@api.get("/api/me", auth=ANY, tags=["account"])
def me(ctx):
    """Current user profile."""
    return _public_user(ctx.user)


@api.patch("/api/me", auth=ANY, body=ProfileIn, tags=["account"])
def update_me(ctx):
    """Update name/phone or change password."""
    b, db = ctx.body, get_db()
    vals = {}
    if b.name:
        vals["name"] = b.name
    if b.phone and b.phone != ctx.user["phone"]:
        if db.one("SELECT id FROM users WHERE phone = ? AND id <> ?", (b.phone, ctx.user_id)):
            raise ApiError(409, "phone_taken", "Another account uses this phone number")
        vals["phone"] = b.phone
    if b.new_password:
        row = db.one("SELECT password_hash FROM users WHERE id = ?", (ctx.user_id,))
        if not b.current_password or not verify_password(b.current_password, row["password_hash"]):
            raise ApiError(400, "wrong_password", "Current password is incorrect")
        vals["password_hash"] = hash_password(b.new_password)
    db.update("users", ctx.user_id, vals)
    return _public_user(db.one("SELECT * FROM users WHERE id = ?", (ctx.user_id,)))


# ------------------------------------------------------------- favorites
@api.get("/api/me/favorites", auth=ANY, tags=["account"])
def favorites(ctx):
    """Favourite routes and stops."""
    db = get_db()
    routes = [network.get(r["route_id"]) for r in db.all("SELECT route_id FROM favorite_routes WHERE user_id = ? ORDER BY created_at", (ctx.user_id,))]
    stops = db.all("SELECT s.id, s.code, s.name, s.name_ur, s.lat, s.lon, s.is_demo FROM favorite_stops f JOIN stops s ON s.id = f.stop_id "
                   "WHERE f.user_id = ? ORDER BY f.created_at", (ctx.user_id,))
    return {"routes": [r.summary() for r in routes if r], "stops": [{**s, "is_demo": bool(s["is_demo"])} for s in stops]}


def _fav(table: str, col: str, check_sql: str, what: str):
    def add(ctx):
        db = get_db()
        if not db.one(check_sql, (ctx.body.id,)):
            raise not_found(what)
        if not db.one(f"SELECT 1 AS x FROM {table} WHERE user_id = ? AND {col} = ?", (ctx.user_id, ctx.body.id)):
            db.execute(f"INSERT INTO {table} (user_id, {col}, created_at) VALUES (?, ?, ?)", (ctx.user_id, ctx.body.id, iso()))
        return {"ok": True}

    def remove(ctx):
        get_db().execute(f"DELETE FROM {table} WHERE user_id = ? AND {col} = ?", (ctx.user_id, ctx.path["id"]))
        return {"ok": True}
    add.__name__, remove.__name__ = f"add_{table}", f"remove_{table}"
    return add, remove


_add_r, _rm_r = _fav("favorite_routes", "route_id", "SELECT id FROM routes WHERE id = ?", "Route")
_add_s, _rm_s = _fav("favorite_stops", "stop_id", "SELECT id FROM stops WHERE id = ?", "Stop")
api.post("/api/me/favorites/routes", auth=ANY, body=FavoriteIn, tags=["account"], summary="Add a favourite route")(_add_r)
api.delete("/api/me/favorites/routes/{id:int}", auth=ANY, tags=["account"], summary="Remove a favourite route")(_rm_r)
api.post("/api/me/favorites/stops", auth=ANY, body=FavoriteIn, tags=["account"], summary="Add a favourite stop")(_add_s)
api.delete("/api/me/favorites/stops/{id:int}", auth=ANY, tags=["account"], summary="Remove a favourite stop")(_rm_s)


# --------------------------------------------------------------- history
@api.get("/api/me/history", auth=ANY, query=PageQ, tags=["account"])
def history(ctx):
    """Journey history (most recent first)."""
    return get_db().all("SELECT id, origin_label, dest_label, route_codes, created_at FROM journey_history WHERE user_id = ? "
                        "ORDER BY created_at DESC LIMIT ?", (ctx.user_id, ctx.query.limit))


@api.post("/api/me/history", auth=ANY, body=HistoryIn, tags=["account"], status=201)
def add_history(ctx):
    """Record a journey the user started."""
    b = ctx.body
    hid = get_db().insert("journey_history", {"user_id": ctx.user_id, "origin_label": b.origin_label, "dest_label": b.dest_label,
                                              "route_codes": b.route_codes, "created_at": iso()})
    return {"id": hid}


@api.delete("/api/me/history", auth=ANY, tags=["account"])
def clear_history(ctx):
    """Delete all journey history."""
    get_db().execute("DELETE FROM journey_history WHERE user_id = ?", (ctx.user_id,))
    return {"ok": True}


# --------------------------------------------------------- notifications
@api.get("/api/me/notification-preferences", auth=ANY, tags=["notifications"])
def get_notification_prefs(ctx):
    """Notification preferences."""
    return get_prefs(ctx.user_id)


@api.put("/api/me/notification-preferences", auth=ANY, body=PrefsIn, tags=["notifications"])
def put_notification_prefs(ctx):
    """Update notification preferences."""
    get_prefs(ctx.user_id)
    b = ctx.body
    get_db().execute(
        "UPDATE notification_prefs SET approaching = ?, approaching_lead_min = ?, delays = ?, disruptions = ?, schedule_changes = ? WHERE user_id = ?",
        (b.approaching, b.approaching_lead_min, b.delays, b.disruptions, b.schedule_changes, ctx.user_id))
    return get_prefs(ctx.user_id)


@api.get("/api/me/notifications", auth=ANY, query=PageQ, tags=["notifications"])
def notifications(ctx):
    """In-app notification inbox."""
    db = get_db()
    rows = db.all("SELECT id, kind, title, body, data_json, pushed, created_at, read_at FROM notifications WHERE user_id = ? "
                  "ORDER BY created_at DESC LIMIT ?", (ctx.user_id, ctx.query.limit))
    unread = db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (ctx.user_id,))
    return {"unread": unread, "items": [{**{k: v for k, v in r.items() if k != "data_json"}, "pushed": bool(r["pushed"]),
                                         "data": json.loads(r["data_json"] or "{}")} for r in rows]}


@api.post("/api/me/notifications/read", auth=ANY, tags=["notifications"])
def mark_read(ctx):
    """Mark all notifications as read."""
    get_db().execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (iso(), ctx.user_id))
    return {"ok": True}


@api.post("/api/me/devices", auth=ANY, body=DeviceTokenIn, tags=["notifications"], status=201)
def register_device(ctx):
    """Register an FCM device token for push notifications."""
    db = get_db()
    db.execute("DELETE FROM device_tokens WHERE token = ?", (ctx.body.token,))
    db.insert("device_tokens", {"user_id": ctx.user_id, "token": ctx.body.token, "platform": ctx.body.platform, "created_at": iso()})
    return {"ok": True, "push_enabled_on_server": settings.fcm_configured}


@api.get("/api/me/watches", auth=ANY, tags=["notifications"])
def list_watches(ctx):
    """Active 'notify me when the bus approaches' requests."""
    return get_db().all("SELECT w.*, s.name AS stop_name, r.code AS route_code FROM stop_watches w JOIN stops s ON s.id = w.stop_id "
                        "JOIN routes r ON r.id = w.route_id WHERE w.user_id = ? AND w.expires_at > ? ORDER BY w.created_at DESC",
                        (ctx.user_id, iso()))


@api.post("/api/me/watches", auth=ANY, body=WatchIn, tags=["notifications"], status=201)
def add_watch(ctx):
    """Ask to be notified when a bus on a route approaches a stop."""
    b = ctx.body
    route = network.get(b.route_id)
    if not route or route.stop_index(b.stop_id) is None:
        raise ApiError(422, "stop_not_on_route", "That stop is not on this route")
    db = get_db()
    db.execute("DELETE FROM stop_watches WHERE user_id = ? AND route_id = ? AND stop_id = ?", (ctx.user_id, b.route_id, b.stop_id))
    wid = db.insert("stop_watches", {"user_id": ctx.user_id, "route_id": b.route_id, "stop_id": b.stop_id, "bus_id": b.bus_id,
                                     "lead_min": b.lead_min, "created_at": iso(), "expires_at": iso(utcnow() + dt.timedelta(hours=b.hours))})
    return {"id": wid}


@api.delete("/api/me/watches/{id:int}", auth=ANY, tags=["notifications"])
def delete_watch(ctx):
    """Cancel a watch."""
    get_db().execute("DELETE FROM stop_watches WHERE id = ? AND user_id = ?", (ctx.path["id"], ctx.user_id))
    return {"ok": True}
