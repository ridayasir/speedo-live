"""Signed-in passenger features: favourites, journey history, notifications and arrival alerts."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..models import (
    ArrivalWatch,
    BusStop,
    DeviceToken,
    FavoriteRoute,
    FavoriteStop,
    Journey,
    Notification,
    Route,
    User,
    route_stops,
)
from ..schemas import DeviceTokenIn, JourneyIn, PrefsIn, WatchIn, iso, route_out, stop_out
from ..security import get_current_user
from ..services.tracking import utcnow
from ..store import IntegrityError, Session

router = APIRouter(prefix="/api/me", tags=["passenger account"])


@router.get("/favorites")
def favorites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    routes = db.where(FavoriteRoute, user_id=user.id, order_by="created_at")
    stops = db.where(FavoriteStop, user_id=user.id, order_by="created_at")
    return {"routes": [route_out(f.route) for f in routes if f.route],
            "stops": [stop_out(f.stop) for f in stops if f.stop]}


@router.put("/favorites/routes/{route_id}", status_code=204)
def add_fav_route(route_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Route, route_id):
        raise HTTPException(404, "Route not found")
    db.add(FavoriteRoute(user_id=user.id, route_id=route_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


@router.delete("/favorites/routes/{route_id}", status_code=204)
def del_fav_route(route_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.first(FavoriteRoute, user_id=user.id, route_id=route_id)
    if f:
        db.delete(f)
        db.commit()


@router.put("/favorites/stops/{stop_id}", status_code=204)
def add_fav_stop(stop_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(BusStop, stop_id):
        raise HTTPException(404, "Stop not found")
    db.add(FavoriteStop(user_id=user.id, stop_id=stop_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


@router.delete("/favorites/stops/{stop_id}", status_code=204)
def del_fav_stop(stop_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.first(FavoriteStop, user_id=user.id, stop_id=stop_id)
    if f:
        db.delete(f)
        db.commit()


@router.get("/journeys")
def journeys(limit: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.where(Journey, user_id=user.id, order_by="created_at", desc=True, limit=min(limit, 100))
    return [{
        "id": j.id, "created_at": iso(j.created_at),
        "route": route_out(j.route) if j.route else None,
        "from_stop": stop_out(j.from_stop) if j.from_stop else None,
        "to_stop": stop_out(j.to_stop) if j.to_stop else None,
    } for j in rows]


@router.post("/journeys", status_code=201)
def add_journey(body: JourneyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Route, body.route_id):
        raise HTTPException(404, "Route not found")
    j = Journey(user_id=user.id, route_id=body.route_id, from_stop_id=body.from_stop_id, to_stop_id=body.to_stop_id)
    db.add(j)
    db.commit()
    return {"id": j.id}


@router.delete("/journeys", status_code=204)
def clear_journeys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for j in db.where(Journey, user_id=user.id):
        db.delete(j)
    db.commit()


@router.get("/notification-preferences")
def get_prefs(user: User = Depends(get_current_user)):
    return user.notification_prefs


@router.put("/notification-preferences")
def set_prefs(body: PrefsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = dict(user.notification_prefs or {})
    prefs.update({k: v for k, v in body.model_dump().items() if v is not None})
    user.notification_prefs = prefs
    db.commit()
    return prefs


@router.get("/notifications")
def notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = [("read_at", "==", None)] if unread_only else []
    rows = db.where(Notification, *filters, user_id=user.id, order_by="created_at", desc=True, limit=100)
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data,
             "created_at": iso(n.created_at), "read_at": iso(n.read_at), "delivery_status": n.delivery_status}
            for n in rows]


@router.post("/notifications/read", status_code=204)
def mark_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = utcnow()
    for n in db.where(Notification, ("read_at", "==", None), user_id=user.id):
        n.read_at = now
    db.commit()


@router.post("/devices", status_code=204)
def register_device(body: DeviceTokenIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Register an FCM device token for push notifications."""
    existing = db.first(DeviceToken, token=body.token)
    if existing:
        existing.user_id = user.id
        existing.platform = body.platform
    else:
        db.add(DeviceToken(user_id=user.id, token=body.token, platform=body.platform))
    db.commit()


@router.get("/watches")
def list_watches(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.where(ArrivalWatch, user_id=user.id, is_active=True)
    return [{"id": w.id, "stop_id": w.stop_id, "route_id": w.route_id, "bus_id": w.bus_id,
             "minutes_before": w.minutes_before, "expires_at": iso(w.expires_at)} for w in rows]


@router.post("/watches", status_code=201)
def add_watch(body: WatchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask to be notified when a bus on this route is a few minutes from this stop."""
    if not route_stops(stop_id=body.stop_id, route_id=body.route_id):
        raise HTTPException(400, "That stop is not on that route")
    w = ArrivalWatch(user_id=user.id, stop_id=body.stop_id, route_id=body.route_id, bus_id=body.bus_id,
                     minutes_before=body.minutes_before, expires_at=utcnow() + timedelta(hours=3))
    db.add(w)
    db.commit()
    return {"id": w.id}


@router.delete("/watches/{watch_id}", status_code=204)
def del_watch(watch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = db.get(ArrivalWatch, watch_id)
    if not w or w.user_id != user.id:
        raise HTTPException(404, "Not found")
    w.is_active = False
    db.commit()
