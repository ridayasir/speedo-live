"""Data models, stored as Cloud Firestore documents (one collection per model).

Field names and relationships match the previous SQL schema, so services and routers use them unchanged.
Route stops are embedded in their route document; route paths are stored as [{lat, lng}, ...]
because Firestore does not allow nested arrays. Unique fields and cascades that the SQL database used
to enforce are enforced by app.store (UNIQUE) and the on_delete hooks below.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from .store import Doc, Session, TrackedList, store


class Role(str, enum.Enum):
    passenger = "passenger"
    driver = "driver"
    admin = "admin"


class BusStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    maintenance = "maintenance"
    out_of_service = "out_of_service"


class RouteStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    inactive = "inactive"


class TripStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    interrupted = "interrupted"


class DataSource(str, enum.Enum):
    demo = "demo"
    driver = "driver"
    provider = "provider"


class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    disruption = "disruption"


DEFAULT_PREFS = {
    "bus_approaching": True,
    "arrival_minutes_before": 5,
    "delays": True,
    "disruptions": True,
    "schedule_changes": True,
}

TS = {"created_at": None, "updated_at": None}


def _find(model, **eq):
    for o in store.cached(model):
        if all(getattr(o, k) == v for k, v in eq.items()):
            return o
    return None


def _delete_all(db: Session, rows) -> None:
    for r in rows:
        db.delete(r)


# ----------------------------------------------------------------------------- people
class User(Doc):
    """App profile of a Firebase Authentication account (firebase_uid). Passwords live only in Firebase.

    auth_email is the account's Firebase sign-in email. Accounts registered with only a phone number get
    an internal address (<digits>@phone.speedolive.invalid) because Firebase passwords need an email.
    """

    __collection__ = "users"
    FIELDS = {"firebase_uid": None, "auth_email": None, "email": None, "phone": None, "full_name": "", "role": Role.passenger,
              "is_active": True, "notification_prefs": lambda: dict(DEFAULT_PREFS), "last_login_at": None, **TS}
    ENUMS = {"role": Role}
    UNIQUE = (("firebase_uid",), ("auth_email",), ("email",), ("phone",))

    @property
    def driver(self) -> Driver | None:
        return _find(Driver, user_id=self.id)


class Driver(Doc):
    __collection__ = "drivers"
    FIELDS = {"user_id": None, "license_number": "", "employee_code": None, "is_active": True,
              "location_consent_at": None, "assigned_bus_id": None, **TS}
    UNIQUE = (("user_id",), ("license_number",), ("employee_code",), ("assigned_bus_id",))

    @property
    def user(self) -> User | None:
        return store.get(User, self.user_id)

    @property
    def assigned_bus(self) -> Bus | None:
        return store.get(Bus, self.assigned_bus_id)


# ----------------------------------------------------------------------------- network
class BusStop(Doc):
    __collection__ = "bus_stops"
    FIELDS = {"code": "", "name": "", "name_ur": None, "lat": 0.0, "lng": 0.0, "is_demo": False,
              "source_reference": None, **TS}
    UNIQUE = (("code",),)

    def on_delete(self, db: Session) -> None:
        _delete_all(db, db.where(FavoriteStop, stop_id=self.id))
        _delete_all(db, db.where(ServiceAlert, stop_id=self.id))
        _delete_all(db, db.where(ArrivalWatch, stop_id=self.id))
        for r in db.all(Route):
            if r.start_stop_id == self.id:
                r.start_stop_id = None
            if r.end_stop_id == self.id:
                r.end_stop_id = None
        for field in ("from_stop_id", "to_stop_id"):
            for j in db.where(Journey, **{field: self.id}):
                setattr(j, field, None)


class RouteStop:
    """A stop on a route (embedded in the route document)."""

    FIELDS = ("stop_id", "sequence", "distance_from_start_m", "offset_minutes", "is_major")

    def __init__(self, stop_id=None, sequence=0, distance_from_start_m=0.0, offset_minutes=0.0, is_major=False,
                 stop: BusStop | None = None, route: Route | None = None):
        object.__setattr__(self, "route", route)
        object.__setattr__(self, "stop_id", stop_id if stop_id is not None else (stop.id if stop else None))
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "distance_from_start_m", float(distance_from_start_m or 0))
        object.__setattr__(self, "offset_minutes", float(offset_minutes or 0))
        object.__setattr__(self, "is_major", bool(is_major))

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)
        if k in self.FIELDS and self.route is not None and self.route._persisted is not None:
            store.mark(self.route)

    @property
    def route_id(self) -> int | None:
        return self.route.id if self.route else None

    @property
    def stop(self) -> BusStop | None:
        return store.get(BusStop, self.stop_id)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.FIELDS}


class RouteStopList(TrackedList):
    def append(self, x: RouteStop):
        object.__setattr__(x, "route", self._owner)
        super().append(x)


class Route(Doc):
    __collection__ = "routes"
    FIELDS = {"code": "", "name": "", "color": "#1d4ed8", "status": RouteStatus.active, "start_stop_id": None,
              "end_stop_id": None, "path": list, "length_m": 0.0, "avg_speed_kmh": None, "fare_pkr": None,
              "is_demo": False, "source_reference": None, **TS}
    ENUMS = {"status": RouteStatus}
    UNIQUE = (("code",),)

    def __init__(self, **kw):
        super().__init__(**kw)
        object.__setattr__(self, "stops", RouteStopList(self))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["path"] = [{"lat": p[0], "lng": p[1]} for p in (self.path or [])]
        d["stops"] = [rs.to_dict() for rs in sorted(self.stops, key=lambda x: x.sequence)]
        return d

    def _load_extra(self, data: dict) -> None:
        object.__setattr__(self, "path", [[p["lat"], p["lng"]] if isinstance(p, dict) else list(p)
                                          for p in (data.get("path") or [])])
        lst = RouteStopList(self)
        for d in data.get("stops") or []:
            list.append(lst, RouteStop(route=self, **{k: d.get(k) for k in RouteStop.FIELDS}))
        object.__setattr__(self, "stops", lst)

    def _restore_extra(self, fresh: Route) -> None:
        lst = RouteStopList(self)
        for rs in fresh.stops:
            object.__setattr__(rs, "route", self)
            list.append(lst, rs)
        object.__setattr__(self, "stops", lst)

    @property
    def schedules(self) -> list[Schedule]:
        return [s for s in store.cached(Schedule) if s.route_id == self.id]

    @property
    def start_stop(self) -> BusStop | None:
        return store.get(BusStop, self.start_stop_id)

    @property
    def end_stop(self) -> BusStop | None:
        return store.get(BusStop, self.end_stop_id)

    def on_delete(self, db: Session) -> None:
        _delete_all(db, self.schedules)
        _delete_all(db, db.where(ServiceAlert, route_id=self.id))
        _delete_all(db, db.where(FavoriteRoute, route_id=self.id))
        _delete_all(db, db.where(ArrivalWatch, route_id=self.id))
        _delete_all(db, db.where(Trip, route_id=self.id))
        for b in db.where(Bus, route_id=self.id):
            b.route_id = None
        for j in db.where(Journey, route_id=self.id):
            j.route_id = None


def route_stops(stop_id: int | None = None, route_id: int | None = None) -> list[RouteStop]:
    """All route-stop links, optionally for one stop and/or one route."""
    out = []
    for r in store.cached(Route):
        if route_id is not None and r.id != route_id:
            continue
        out += [rs for rs in r.stops if stop_id is None or rs.stop_id == stop_id]
    return out


class Bus(Doc):
    __collection__ = "buses"
    FIELDS = {"bus_number": "", "registration_number": None, "capacity": None, "status": BusStatus.active,
              "route_id": None, "gps_device_id": None, "is_demo": False, "last_lat": None, "last_lng": None,
              "last_speed_mps": None, "last_heading": None, "last_accuracy_m": None, "last_gps_at": None, **TS}
    ENUMS = {"status": BusStatus}
    UNIQUE = (("bus_number",), ("registration_number",), ("gps_device_id",))
    VOLATILE = frozenset({"last_lat", "last_lng", "last_speed_mps", "last_heading", "last_accuracy_m", "last_gps_at"})
    WRITE_EVERY = 900  # 15 min: ~50 simulated buses stay inside the free 20k writes/day

    @property
    def route(self) -> Route | None:
        return store.get(Route, self.route_id)

    @property
    def driver(self) -> Driver | None:
        return _find(Driver, assigned_bus_id=self.id)

    def on_delete(self, db: Session) -> None:
        _delete_all(db, db.where(Trip, bus_id=self.id))
        _delete_all(db, db.where(ArrivalWatch, bus_id=self.id))
        for d in db.where(Driver, assigned_bus_id=self.id):
            d.assigned_bus_id = None


# ----------------------------------------------------------------------------- operations
class Trip(Doc):
    """Active trips are mirrored in memory; finished trips are read from Firestore on demand."""

    __collection__ = "trips"
    FIELDS = {"bus_id": None, "route_id": None, "driver_id": None, "status": TripStatus.active,
              "source": DataSource.driver, "direction": "forward", "started_at": None, "ended_at": None,
              "last_update_at": None, "progress_m": 0.0, "max_delay_minutes": 0.0, "delay_notified": False,
              "gps_points": 0, "end_reason": None, **TS}
    ENUMS = {"status": TripStatus, "source": DataSource}
    CACHE_FILTERS = (("status", "==", "active"),)
    VOLATILE = frozenset({"progress_m", "last_update_at", "gps_points", "max_delay_minutes"})
    WRITE_EVERY = 900  # 15 min: ~50 simulated buses stay inside the free 20k writes/day

    def __init__(self, **kw):
        super().__init__(**kw)
        if self.started_at is None:
            object.__setattr__(self, "started_at", datetime.now(timezone.utc))

    @classmethod
    def keep_cached(cls, obj) -> bool:
        return obj.status == TripStatus.active

    @property
    def bus(self) -> Bus | None:
        return store.get(Bus, self.bus_id)

    @property
    def route(self) -> Route | None:
        return store.get(Route, self.route_id)

    @property
    def driver(self) -> Driver | None:
        return store.get(Driver, self.driver_id)

    def on_delete(self, db: Session) -> None:
        _delete_all(db, db.where(GpsLocation, trip_id=self.id))


class GpsLocation(Doc):
    """GPS history. The document id is <bus_id>-<epoch ms>, so a bus cannot store two fixes for one instant."""

    __collection__ = "gps_locations"
    FIELDS = {"trip_id": None, "bus_id": None, "lat": 0.0, "lng": 0.0, "accuracy_m": None, "speed_mps": None,
              "heading": None, "recorded_at": None, "received_at": None}
    CACHED = False
    TIMESTAMPS = False
    STR_ID = True

    def new_id(self) -> str:
        return f"{self.bus_id}-{int(self.recorded_at.timestamp() * 1000)}"


class Schedule(Doc):
    __collection__ = "schedules"
    FIELDS = {"route_id": None, "days": "mon,tue,wed,thu,fri,sat,sun", "first_departure": None,
              "last_departure": None, "frequency_minutes": 15, "valid_from": None, "valid_to": None, "notes": None,
              "is_demo": False, **TS}
    TIMES = ("first_departure", "last_departure")

    @property
    def route(self) -> Route | None:
        return store.get(Route, self.route_id)


class Notification(Doc):
    __collection__ = "notifications"
    FIELDS = {"user_id": None, "kind": "", "title": "", "body": "", "data": dict, "dedupe_key": None,
              "delivery_status": "stored", "created_at": None, "read_at": None}
    CACHED = False
    TIMESTAMPS = False


class DeviceToken(Doc):
    __collection__ = "device_tokens"
    FIELDS = {"user_id": None, "token": "", "platform": "android", **TS}
    UNIQUE = (("token",),)


class FavoriteRoute(Doc):
    __collection__ = "favorite_routes"
    FIELDS = {"user_id": None, "route_id": None, "created_at": None}
    UNIQUE = (("user_id", "route_id"),)
    TIMESTAMPS = False

    @property
    def route(self) -> Route | None:
        return store.get(Route, self.route_id)


class FavoriteStop(Doc):
    __collection__ = "favorite_stops"
    FIELDS = {"user_id": None, "stop_id": None, "created_at": None}
    UNIQUE = (("user_id", "stop_id"),)
    TIMESTAMPS = False

    @property
    def stop(self) -> BusStop | None:
        return store.get(BusStop, self.stop_id)


class ServiceAlert(Doc):
    __collection__ = "service_alerts"
    FIELDS = {"route_id": None, "stop_id": None, "severity": AlertSeverity.info, "title": "", "message": "",
              "starts_at": None, "ends_at": None, "is_active": True, "created_by": None, **TS}
    ENUMS = {"severity": AlertSeverity}


class Journey(Doc):
    """Passenger journey history (searches the user chose to track)."""

    __collection__ = "journeys"
    FIELDS = {"user_id": None, "route_id": None, "from_stop_id": None, "to_stop_id": None, "created_at": None}
    CACHED = False
    TIMESTAMPS = False

    @property
    def route(self) -> Route | None:
        return store.get(Route, self.route_id)

    @property
    def from_stop(self) -> BusStop | None:
        return store.get(BusStop, self.from_stop_id)

    @property
    def to_stop(self) -> BusStop | None:
        return store.get(BusStop, self.to_stop_id)


class ArrivalWatch(Doc):
    """A passenger asked to be told when a bus approaches a stop."""

    __collection__ = "arrival_watches"
    FIELDS = {"user_id": None, "stop_id": None, "route_id": None, "bus_id": None, "minutes_before": 5,
              "is_active": True, "notified_approaching": False, "created_at": None, "expires_at": None}
    TIMESTAMPS = False
    CACHE_FILTERS = (("is_active", "==", True),)

    @classmethod
    def keep_cached(cls, obj) -> bool:
        return obj.is_active


class AuditLog(Doc):
    __collection__ = "audit_logs"
    FIELDS = {"user_id": None, "action": "", "entity": "", "entity_id": None, "details": dict, "created_at": None}
    CACHED = False
    TIMESTAMPS = False
