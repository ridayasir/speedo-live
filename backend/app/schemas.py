"""Request models (pydantic) — used for validation and the OpenAPI document."""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PK_PHONE_RE = re.compile(r"^(?:\+92|0)3\d{9}$")
HM_RE = r"^([01]\d|2[0-3]):[0-5]\d$"
HEX_RE = r"^#[0-9A-Fa-f]{6}$"
DAYS_RE = r"^(MON|TUE|WED|THU|FRI|SAT|SUN)(,(MON|TUE|WED|THU|FRI|SAT|SUN))*$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def normalize_phone(v: str) -> str:
    v = re.sub(r"[\s-]", "", v)
    if not PK_PHONE_RE.match(v):
        raise ValueError("enter a Pakistani mobile number like 03001234567")
    return "0" + v[3:] if v.startswith("+92") else v


# ---------------------------------------------------------------- auth
class RegisterIn(Strict):
    name: str = Field(min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = None
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is None or v == "":
            return None
        if not EMAIL_RE.match(v):
            raise ValueError("enter a valid email address")
        return v.lower()

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if v else None

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("password must contain letters and numbers")
        return v

    @model_validator(mode="after")
    def _one_contact(self):
        if not self.email and not self.phone:
            raise ValueError("provide an email address or a phone number")
        return self


class LoginIn(Strict):
    identifier: str = Field(min_length=3, max_length=255, description="Email address or phone number")
    password: str = Field(min_length=1, max_length=128)


class ProfileIn(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = None
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if v else None


# --------------------------------------------------------------- public
class StopSearchQ(BaseModel):
    q: str | None = Field(default=None, max_length=80, description="Text to match in stop name or code")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=2000, ge=50, le=20000)
    limit: int = Field(default=20, ge=1, le=100)


class Place(Strict):
    stop_id: int | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    label: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _any(self):
        if self.stop_id is None and (self.lat is None or self.lon is None):
            raise ValueError("give a stop_id or both lat and lon")
        return self


class PlanIn(Strict):
    origin: Place
    destination: Place
    save_history: bool = True


class BusesQ(BaseModel):
    route_id: int | None = None
    include_idle: bool = False


class StreamQ(BaseModel):
    route_id: str | None = Field(default=None, description="Comma-separated route ids")
    bus_id: str | None = Field(default=None, description="Comma-separated bus ids")
    ticket: str | None = Field(default=None, description="Admin stream ticket")


class TimetableQ(BaseModel):
    route_id: int
    stop_id: int | None = None
    date: dt.date | None = None


class ArrivalsQ(BaseModel):
    route_id: int | None = None


# --------------------------------------------------------------- driver
class TripStartIn(Strict):
    direction: Literal["outbound", "inbound"] = "outbound"


class TripEndIn(Strict):
    reason: Literal["completed", "interrupted"] = "completed"


class GpsPointIn(Strict):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=10000)
    speed_mps: float | None = Field(default=None, ge=0, le=100)
    heading: float | None = Field(default=None, ge=0, le=360)
    recorded_at: dt.datetime

    @field_validator("recorded_at")
    @classmethod
    def _tz(cls, v: dt.datetime):
        if v.tzinfo is None:
            raise ValueError("recorded_at must include a timezone (ISO 8601, e.g. 2026-11-04T10:00:00Z)")
        return v


class GpsBatchIn(Strict):
    points: list[GpsPointIn] = Field(min_length=1, max_length=100)


class ConsentIn(Strict):
    accepted: bool


# ------------------------------------------------------------ passenger
class FavoriteIn(Strict):
    id: int


class PrefsIn(Strict):
    approaching: bool = True
    approaching_lead_min: int = Field(default=5, ge=1, le=30)
    delays: bool = True
    disruptions: bool = True
    schedule_changes: bool = True


class DeviceTokenIn(Strict):
    token: str = Field(min_length=10, max_length=512)
    platform: Literal["android", "ios", "web"] = "android"


class WatchIn(Strict):
    route_id: int
    stop_id: int
    bus_id: int | None = None
    lead_min: int = Field(default=5, ge=1, le=30)
    hours: float = Field(default=2, gt=0, le=12, description="How long the watch stays active")


class HistoryIn(Strict):
    origin_label: str = Field(min_length=1, max_length=160)
    dest_label: str = Field(min_length=1, max_length=160)
    route_codes: str | None = Field(default=None, max_length=120)


# ---------------------------------------------------------------- admin
class StopIn(Strict):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=160)
    name_ur: str | None = Field(default=None, max_length=160)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    status: Literal["active", "closed"] = "active"


class RouteIn(Strict):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    color: str = Field(default="#1D4ED8", pattern=HEX_RE)
    status: Literal["active", "suspended", "inactive"] = "active"
    avg_speed_kmh: float = Field(default=18, ge=5, le=60)
    verified: bool = False
    source: str | None = Field(default=None, max_length=255)
    stop_ids: list[int] = Field(default_factory=list, description="Ordered stop ids (first = start, last = end)")
    shape: list[tuple[float, float]] | None = Field(default=None, description="Optional [[lat,lon],...] road geometry")

    @model_validator(mode="after")
    def _check(self):
        if len(set(self.stop_ids)) != len(self.stop_ids):
            raise ValueError("a stop can only appear once on a route")
        if self.verified and not self.source:
            raise ValueError("verified routes need a source (e.g. the official notice they come from)")
        return self


class RoutePatch(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    color: str | None = Field(default=None, pattern=HEX_RE)
    status: Literal["active", "suspended", "inactive"] | None = None
    avg_speed_kmh: float | None = Field(default=None, ge=5, le=60)
    verified: bool | None = None
    source: str | None = Field(default=None, max_length=255)
    stop_ids: list[int] | None = None
    shape: list[tuple[float, float]] | None = None


class BusIn(Strict):
    bus_number: str = Field(min_length=1, max_length=32)
    registration_no: str | None = Field(default=None, max_length=32)
    capacity: int | None = Field(default=None, ge=1, le=300)
    route_id: int | None = None
    driver_id: int | None = None
    status: Literal["active", "inactive", "maintenance"] = "active"
    gps_device_id: str | None = Field(default=None, max_length=64)


class BusPatch(Strict):
    bus_number: str | None = Field(default=None, min_length=1, max_length=32)
    registration_no: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=300)
    route_id: int | None = None
    driver_id: int | None = None
    status: Literal["active", "inactive", "maintenance"] | None = None
    gps_device_id: str | None = None
    clear_route: bool = False
    clear_driver: bool = False


class DriverIn(Strict):
    name: str = Field(min_length=2, max_length=120)
    email: str | None = None
    phone: str
    password: str = Field(min_length=8, max_length=128)
    employee_code: str = Field(min_length=1, max_length=32)
    license_no: str | None = Field(default=None, max_length=40)
    bus_id: int | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if not v:
            return None
        if not EMAIL_RE.match(v):
            raise ValueError("enter a valid email address")
        return v.lower()


class DriverPatch(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = None
    license_no: str | None = None
    is_active: bool | None = None
    bus_id: int | None = None
    clear_bus: bool = False
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if v else None


class ScheduleIn(Strict):
    route_id: int
    days: str = Field(default="MON,TUE,WED,THU,FRI,SAT,SUN", pattern=DAYS_RE)
    first_departure: str = Field(pattern=HM_RE)
    last_departure: str = Field(pattern=HM_RE)
    headway_min: int = Field(ge=1, le=240)
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    notes: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _order(self):
        if self.last_departure < self.first_departure:
            raise ValueError("last_departure must be after first_departure")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self


class AlertIn(Strict):
    title: str = Field(min_length=3, max_length=160)
    body: str | None = Field(default=None, max_length=2000)
    severity: Literal["info", "delay", "disruption", "suspension", "schedule_change"] = "info"
    route_id: int | None = None
    stop_id: int | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    notify: bool = True


class AlertPatch(Strict):
    is_active: bool | None = None
    ends_at: dt.datetime | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = None


class ImportQ(BaseModel):
    dry_run: bool = True
    verified: bool = False
    source: str = Field(min_length=3, max_length=255, description="Where the data comes from (official notice, date)")


class ReportQ(BaseModel):
    date: dt.date | None = None
    format: Literal["json", "csv"] = "json"


COMPLAINT_CATEGORIES = Literal["rash_driving", "rude_behaviour", "harassment", "overcharging", "skipped_stop",
                               "phone_smoking", "late", "bus_condition", "other"]


class ComplaintIn(Strict):
    bus_number: str = Field(min_length=1, max_length=32, description="Number painted on the bus, e.g. SP-101")
    category: COMPLAINT_CATEGORIES
    description: str = Field(min_length=10, max_length=2000)
    location: str | None = Field(default=None, max_length=160, description="Stop or place where it happened")
    incident_at: dt.datetime | None = Field(default=None, description="When it happened (default: now)")
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = None

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if v else None

    @field_validator("incident_at")
    @classmethod
    def _when(cls, v):
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone(dt.timedelta(hours=5)))  # local Pakistan time
        now = dt.datetime.now(dt.timezone.utc)
        if v > now + dt.timedelta(minutes=10):
            raise ValueError("the incident time can't be in the future")
        if v < now - dt.timedelta(days=30):
            raise ValueError("complaints must be filed within 30 days of the incident")
        return v


class ComplaintPatch(Strict):
    status: Literal["new", "in_review", "resolved", "rejected"] | None = None
    admin_note: str | None = Field(default=None, max_length=2000, description="Reply shown to the passenger")


class ComplaintsQ(BaseModel):
    status: Literal["new", "in_review", "resolved", "rejected", "open", "all"] = "open"
    driver_id: int | None = None
    bus_id: int | None = None
    limit: int = Field(default=200, ge=1, le=1000)


class PageQ(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
