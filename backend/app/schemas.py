"""Request bodies (validated by pydantic) and response serializers."""
from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from .models import (
    AlertSeverity,
    Bus,
    BusStatus,
    BusStop,
    Driver,
    Route,
    RouteStatus,
    Schedule,
    ServiceAlert,
    Trip,
    User,
)

PHONE_PATTERN = r"^\+?[0-9]{10,15}$"


# ----------------------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def need_contact(self):
        if not self.email and not self.phone:
            raise ValueError("Provide an email or a phone number")
        return self


class LoginIn(BaseModel):
    identifier: str = Field(description="Email or phone number", min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PrefsIn(BaseModel):
    bus_approaching: bool | None = None
    arrival_minutes_before: int | None = Field(default=None, ge=1, le=30)
    delays: bool | None = None
    disruptions: bool | None = None
    schedule_changes: bool | None = None


class DeviceTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=512)
    platform: str = Field(default="android", pattern="^(android|web|ios)$")


class WatchIn(BaseModel):
    stop_id: int
    route_id: int
    bus_id: int | None = None
    minutes_before: int = Field(default=5, ge=1, le=30)


class JourneyIn(BaseModel):
    route_id: int
    from_stop_id: int | None = None
    to_stop_id: int | None = None


# ----------------------------------------------------------------------------- planner
class PlanIn(BaseModel):
    from_lat: float | None = Field(default=None, ge=-90, le=90)
    from_lng: float | None = Field(default=None, ge=-180, le=180)
    from_stop_id: int | None = None
    to_lat: float | None = Field(default=None, ge=-90, le=90)
    to_lng: float | None = Field(default=None, ge=-180, le=180)
    to_stop_id: int | None = None
    from_label: str | None = None
    to_label: str | None = None

    @model_validator(mode="after")
    def need_ends(self):
        if self.from_stop_id is None and (self.from_lat is None or self.from_lng is None):
            raise ValueError("Provide a starting stop or starting coordinates")
        if self.to_stop_id is None and (self.to_lat is None or self.to_lng is None):
            raise ValueError("Provide a destination stop or destination coordinates")
        return self


# ----------------------------------------------------------------------------- driver
class GpsPointIn(BaseModel):
    lat: float
    lng: float
    recorded_at: datetime
    accuracy_m: float | None = Field(default=None, ge=0)
    speed_mps: float | None = None
    heading: float | None = Field(default=None, ge=0, le=360)


class GpsBatchIn(BaseModel):
    points: list[GpsPointIn] = Field(min_length=1, max_length=500)


class TripStartIn(BaseModel):
    consent: bool = Field(description="Driver confirms consent to share the bus location during this trip")


class TripEndIn(BaseModel):
    reason: str = Field(default="completed", max_length=64)


# ----------------------------------------------------------------------------- admin
class BusIn(BaseModel):
    bus_number: str = Field(min_length=1, max_length=32)
    registration_number: str | None = Field(default=None, max_length=32)
    capacity: int | None = Field(default=None, ge=1, le=300)
    status: BusStatus = BusStatus.active
    route_id: int | None = None
    gps_device_id: str | None = Field(default=None, max_length=64)
    is_demo: bool = False


class BusPatch(BaseModel):
    bus_number: str | None = Field(default=None, min_length=1, max_length=32)
    registration_number: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=300)
    status: BusStatus | None = None
    route_id: int | None = None
    gps_device_id: str | None = None
    driver_id: int | None = Field(default=None, description="Set to 0 to unassign the driver")


class StopIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=160)
    name_ur: str | None = None
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    is_demo: bool = False
    source_reference: str | None = None


class StopPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    name_ur: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    source_reference: str | None = None


class RouteStopIn(BaseModel):
    stop_id: int
    offset_minutes: float = Field(default=0, ge=0)
    is_major: bool = False


class RouteIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=200)
    color: str = Field(default="#1d4ed8", pattern=r"^#[0-9a-fA-F]{6}$")
    status: RouteStatus = RouteStatus.active
    fare_pkr: float | None = Field(default=None, ge=0)
    path: list[list[float]] | None = Field(default=None, description="[[lat, lng], ...] road geometry")
    stops: list[RouteStopIn] = Field(default_factory=list, description="Ordered stops; first is the start, last the end")
    is_demo: bool = False
    source_reference: str | None = None

    @field_validator("path")
    @classmethod
    def check_path(cls, v):
        if v is None:
            return v
        for p in v:
            if len(p) != 2 or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180):
                raise ValueError("path points must be [lat, lng]")
        return v


class RoutePatch(BaseModel):
    code: str | None = None
    name: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    status: RouteStatus | None = None
    fare_pkr: float | None = None
    path: list[list[float]] | None = None
    stops: list[RouteStopIn] | None = None
    source_reference: str | None = None


class ScheduleIn(BaseModel):
    route_id: int
    days: str = Field(default="mon,tue,wed,thu,fri,sat,sun", pattern=r"^(mon|tue|wed|thu|fri|sat|sun)(,(mon|tue|wed|thu|fri|sat|sun))*$")
    first_departure: time
    last_departure: time
    frequency_minutes: int = Field(default=15, ge=1, le=240)
    notes: str | None = None
    is_demo: bool = False

    @model_validator(mode="after")
    def order(self):
        if self.last_departure < self.first_departure:
            raise ValueError("last_departure must be after first_departure")
        return self


class DriverIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str = Field(pattern=PHONE_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    license_number: str = Field(min_length=3, max_length=64)
    employee_code: str | None = None
    bus_id: int | None = None


class DriverPatch(BaseModel):
    full_name: str | None = None
    phone: str | None = Field(default=None, pattern=PHONE_PATTERN)
    license_number: str | None = None
    employee_code: str | None = None
    is_active: bool | None = None
    bus_id: int | None = Field(default=None, description="Set to 0 to unassign")
    route_id: int | None = Field(default=None, description="Assigns this route to the driver's bus")
    password: str | None = Field(default=None, min_length=8, max_length=128)


class AlertIn(BaseModel):
    route_id: int | None = None
    stop_id: int | None = None
    severity: AlertSeverity = AlertSeverity.info
    title: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=3, max_length=2000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True


# ----------------------------------------------------------------------------- serializers
def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def user_out(u: User) -> dict:
    return {
        "id": u.id, "full_name": u.full_name, "email": u.email, "phone": u.phone, "role": u.role.value,
        "is_active": u.is_active, "notification_prefs": u.notification_prefs, "created_at": iso(u.created_at),
    }


def stop_out(s: BusStop) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "name_ur": s.name_ur, "lat": s.lat, "lng": s.lng,
            "is_demo": s.is_demo, "source_reference": s.source_reference}


def route_out(r: Route, detail: bool = False) -> dict:
    d = {
        "id": r.id, "code": r.code, "name": r.name, "color": r.color, "status": r.status.value,
        "start_stop": stop_out(r.start_stop) if r.start_stop else None,
        "end_stop": stop_out(r.end_stop) if r.end_stop else None,
        "length_m": round(r.length_m or 0), "stop_count": len(r.stops), "fare_pkr": r.fare_pkr,
        "avg_speed_kmh": round(r.avg_speed_kmh, 1) if r.avg_speed_kmh else None,
        "is_demo": r.is_demo, "source_reference": r.source_reference,
    }
    if detail:
        d["path"] = r.path
        d["stops"] = [
            stop_out(rs.stop) | {"sequence": rs.sequence, "distance_m": round(rs.distance_from_start_m),
                                 "offset_minutes": rs.offset_minutes, "is_major": rs.is_major}
            for rs in sorted(r.stops, key=lambda x: x.sequence)
        ]
        d["schedules"] = [schedule_out(s) for s in r.schedules]
    return d


def schedule_out(s: Schedule) -> dict:
    return {
        "id": s.id, "route_id": s.route_id, "days": s.days.split(","),
        "first_departure": s.first_departure.strftime("%H:%M"), "last_departure": s.last_departure.strftime("%H:%M"),
        "frequency_minutes": s.frequency_minutes, "notes": s.notes, "is_demo": s.is_demo,
    }


def bus_admin_out(b: Bus) -> dict:
    return {
        "id": b.id, "bus_number": b.bus_number, "registration_number": b.registration_number,
        "capacity": b.capacity, "status": b.status.value, "route_id": b.route_id,
        "route_code": b.route.code if b.route else None, "gps_device_id": b.gps_device_id, "is_demo": b.is_demo,
        "driver": {"id": b.driver.id, "name": b.driver.user.full_name} if b.driver else None,
        "last_gps_at": iso(b.last_gps_at),
    }


def driver_out(d: Driver, private: bool = True) -> dict:
    out = {
        "id": d.id, "user_id": d.user_id, "full_name": d.user.full_name, "is_active": d.is_active and d.user.is_active,
        "assigned_bus": {"id": d.assigned_bus.id, "bus_number": d.assigned_bus.bus_number,
                         "route_id": d.assigned_bus.route_id} if d.assigned_bus else None,
        "location_consent_at": iso(d.location_consent_at),
    }
    if private:
        out |= {"email": d.user.email, "phone": d.user.phone, "license_number": d.license_number,
                "employee_code": d.employee_code}
    return out


def trip_out(t: Trip) -> dict:
    return {
        "id": t.id, "bus_id": t.bus_id, "bus_number": t.bus.bus_number, "route_id": t.route_id,
        "route_code": t.route.code, "route_name": t.route.name, "driver_id": t.driver_id,
        "status": t.status.value, "source": t.source.value, "started_at": iso(t.started_at),
        "ended_at": iso(t.ended_at), "last_update_at": iso(t.last_update_at), "progress_m": round(t.progress_m),
        "route_length_m": round(t.route.length_m or 0), "max_delay_minutes": round(t.max_delay_minutes, 1),
        "gps_points": t.gps_points, "end_reason": t.end_reason,
    }


def alert_out(a: ServiceAlert) -> dict:
    return {
        "id": a.id, "route_id": a.route_id, "stop_id": a.stop_id, "severity": a.severity.value, "title": a.title,
        "message": a.message, "starts_at": iso(a.starts_at), "ends_at": iso(a.ends_at), "is_active": a.is_active,
        "created_at": iso(a.created_at),
    }
