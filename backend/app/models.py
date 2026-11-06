"""Database models.

Points keep plain lat/lng columns for easy reading plus a PostGIS geography column
(`geog`) used for spatial queries and indexes. `geo.point_wkt` keeps them in sync.
"""
import enum
from datetime import datetime, time

from geoalchemy2 import Geography
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UtcDateTime, is_sqlite


def _geo(kind: str):
    # SQLite has no spatial types; planner.nearby_stops uses lat/lng there instead
    return Text() if is_sqlite else Geography(kind, srid=4326, spatial_index=True)


def _enum(e):
    return Enum(e, values_callable=lambda x: [m.value for m in x], native_enum=False, length=32)


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


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), onupdate=func.now()
    )


DEFAULT_PREFS = {
    "bus_approaching": True,
    "arrival_minutes_before": 5,
    "delays": True,
    "disruptions": True,
    "schedule_changes": True,
}


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.passenger, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_prefs: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_PREFS))
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime())

    admin: Mapped["Administrator | None"] = relationship(back_populates="user", uselist=False)
    driver: Mapped["Driver | None"] = relationship(back_populates="user", uselist=False)


class Administrator(TimestampMixin, Base):
    __tablename__ = "administrators"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    access_level: Mapped[str] = mapped_column(String(32), default="full")
    user: Mapped[User] = relationship(back_populates="admin")


class Driver(TimestampMixin, Base):
    __tablename__ = "drivers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    license_number: Mapped[str] = mapped_column(String(64), unique=True)
    employee_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    location_consent_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    assigned_bus_id: Mapped[int | None] = mapped_column(
        ForeignKey("buses.id", ondelete="SET NULL"), unique=True
    )
    user: Mapped[User] = relationship(back_populates="driver")
    assigned_bus: Mapped["Bus | None"] = relationship(back_populates="driver", foreign_keys=[assigned_bus_id])


class BusStop(TimestampMixin, Base):
    __tablename__ = "bus_stops"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    name_ur: Mapped[str | None] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    geog = mapped_column(_geo("POINT"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(255))


class Route(TimestampMixin, Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    color: Mapped[str] = mapped_column(String(9), default="#1d4ed8")
    status: Mapped[RouteStatus] = mapped_column(_enum(RouteStatus), default=RouteStatus.active)
    start_stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id", ondelete="SET NULL"))
    end_stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id", ondelete="SET NULL"))
    # [[lat, lng], ...] along the road; geog mirrors it for spatial queries
    path: Mapped[list] = mapped_column(JSON, default=list)
    geog = mapped_column(_geo("LINESTRING"), nullable=True)
    length_m: Mapped[float] = mapped_column(Float, default=0)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float)
    fare_pkr: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(255))

    stops: Mapped[list["RouteStop"]] = relationship(
        back_populates="route", order_by="RouteStop.sequence", cascade="all, delete-orphan"
    )
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="route", cascade="all, delete-orphan")
    start_stop: Mapped[BusStop | None] = relationship(foreign_keys=[start_stop_id])
    end_stop: Mapped[BusStop | None] = relationship(foreign_keys=[end_stop_id])


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("route_id", "sequence", name="uq_route_stop_seq"),
        UniqueConstraint("route_id", "stop_id", name="uq_route_stop_stop"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    stop_id: Mapped[int] = mapped_column(ForeignKey("bus_stops.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    distance_from_start_m: Mapped[float] = mapped_column(Float, default=0)
    # scheduled minutes from the first stop
    offset_minutes: Mapped[float] = mapped_column(Float, default=0)
    is_major: Mapped[bool] = mapped_column(Boolean, default=False)

    route: Mapped[Route] = relationship(back_populates="stops")
    stop: Mapped[BusStop] = relationship()


class Bus(TimestampMixin, Base):
    __tablename__ = "buses"
    id: Mapped[int] = mapped_column(primary_key=True)
    bus_number: Mapped[str] = mapped_column(String(32), unique=True)
    registration_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    capacity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[BusStatus] = mapped_column(_enum(BusStatus), default=BusStatus.active)
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id", ondelete="SET NULL"), index=True)
    gps_device_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # latest known position (history lives in gps_locations)
    last_lat: Mapped[float | None] = mapped_column(Float)
    last_lng: Mapped[float | None] = mapped_column(Float)
    last_speed_mps: Mapped[float | None] = mapped_column(Float)
    last_heading: Mapped[float | None] = mapped_column(Float)
    last_accuracy_m: Mapped[float | None] = mapped_column(Float)
    last_gps_at: Mapped[datetime | None] = mapped_column(UtcDateTime())

    route: Mapped[Route | None] = relationship()
    driver: Mapped[Driver | None] = relationship(
        back_populates="assigned_bus", foreign_keys="Driver.assigned_bus_id", uselist=False
    )


class Trip(TimestampMixin, Base):
    __tablename__ = "trips"
    __table_args__ = (Index("ix_trips_bus_status", "bus_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bus_id: Mapped[int] = mapped_column(ForeignKey("buses.id", ondelete="CASCADE"))
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id", ondelete="SET NULL"), index=True)
    status: Mapped[TripStatus] = mapped_column(_enum(TripStatus), default=TripStatus.active, index=True)
    source: Mapped[DataSource] = mapped_column(_enum(DataSource), default=DataSource.driver)
    direction: Mapped[str] = mapped_column(String(16), default="forward")
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    last_update_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    progress_m: Mapped[float] = mapped_column(Float, default=0)
    max_delay_minutes: Mapped[float] = mapped_column(Float, default=0)
    delay_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    gps_points: Mapped[int] = mapped_column(Integer, default=0)
    end_reason: Mapped[str | None] = mapped_column(String(64))

    bus: Mapped[Bus] = relationship()
    route: Mapped[Route] = relationship()
    driver: Mapped[Driver | None] = relationship()


class GpsLocation(Base):
    __tablename__ = "gps_locations"
    __table_args__ = (
        UniqueConstraint("bus_id", "recorded_at", name="uq_gps_bus_time"),
        Index("ix_gps_bus_time", "bus_id", "recorded_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    bus_id: Mapped[int] = mapped_column(ForeignKey("buses.id", ondelete="CASCADE"))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    geog = mapped_column(_geo("POINT"))
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    speed_mps: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime())
    received_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    # comma separated: mon,tue,wed,thu,fri,sat,sun
    days: Mapped[str] = mapped_column(String(64), default="mon,tue,wed,thu,fri,sat,sun")
    first_departure: Mapped[time] = mapped_column(Time)
    last_departure: Mapped[time] = mapped_column(Time)
    frequency_minutes: Mapped[int] = mapped_column(Integer, default=15)
    valid_from: Mapped[datetime | None] = mapped_column(UtcDateTime())
    valid_to: Mapped[datetime | None] = mapped_column(UtcDateTime())
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    route: Mapped[Route] = relationship(back_populates="schedules")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    delivery_status: Mapped[str] = mapped_column(String(32), default="stored")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class DeviceToken(TimestampMixin, Base):
    __tablename__ = "device_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(512), unique=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")


class FavoriteRoute(Base):
    __tablename__ = "favorite_routes"
    __table_args__ = (UniqueConstraint("user_id", "route_id", name="uq_fav_route"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    route: Mapped[Route] = relationship()


class FavoriteStop(Base):
    __tablename__ = "favorite_stops"
    __table_args__ = (UniqueConstraint("user_id", "stop_id", name="uq_fav_stop"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stop_id: Mapped[int] = mapped_column(ForeignKey("bus_stops.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    stop: Mapped[BusStop] = relationship()


class ServiceAlert(TimestampMixin, Base):
    __tablename__ = "service_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id", ondelete="CASCADE"))
    severity: Mapped[AlertSeverity] = mapped_column(_enum(AlertSeverity), default=AlertSeverity.info)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    ends_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Journey(Base):
    """Passenger journey history (searches the user chose to track)."""

    __tablename__ = "journeys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id", ondelete="SET NULL"), index=True)
    from_stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id", ondelete="SET NULL"))
    to_stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    route: Mapped[Route | None] = relationship()
    from_stop: Mapped[BusStop | None] = relationship(foreign_keys=[from_stop_id])
    to_stop: Mapped[BusStop | None] = relationship(foreign_keys=[to_stop_id])


class ArrivalWatch(Base):
    """A passenger asked to be told when a bus approaches a stop."""

    __tablename__ = "arrival_watches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stop_id: Mapped[int] = mapped_column(ForeignKey("bus_stops.id", ondelete="CASCADE"))
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    bus_id: Mapped[int | None] = mapped_column(ForeignKey("buses.id", ondelete="CASCADE"))
    minutes_before: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notified_approaching: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now(), index=True)
