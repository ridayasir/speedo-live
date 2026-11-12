"""Runtime configuration. Every value comes from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
import logging
from dataclasses import dataclass, field

log = logging.getLogger("speedo.config")


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _load_dotenv() -> None:
    """Minimal .env loader so local runs work without extra packages."""
    path = os.environ.get("SPEEDO_ENV_FILE", os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split(" #", 1)[0].strip().strip('"').strip("'")  # allow trailing comments
            os.environ.setdefault(k.strip(), v)


_load_dotenv()


@dataclass
class Settings:
    app_name: str = "Speedo Live"
    env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    # "demo" = seeded sample data + simulated GPS (always labelled DEMO in the UI)
    # "live" = no simulator; positions only from authorised drivers / GPS provider
    mode: str = field(default_factory=lambda: _env("SPEEDO_MODE", "demo"))
    # driver_app | provider  (where real-world positions come from)
    gps_source: str = field(default_factory=lambda: _env("GPS_SOURCE", "driver_app"))
    gps_provider_url: str | None = field(default_factory=lambda: _env("GPS_PROVIDER_URL"))
    gps_provider_token: str | None = field(default_factory=lambda: _env("GPS_PROVIDER_TOKEN"))

    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./data/speedo.db"))
    enable_postgis: bool = field(default_factory=lambda: _bool("ENABLE_POSTGIS", False))
    redis_url: str | None = field(default_factory=lambda: _env("REDIS_URL"))

    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", ""))
    jwt_ttl_minutes: int = field(default_factory=lambda: _int("JWT_TTL_MINUTES", 720))
    cors_origins: list[str] = field(default_factory=lambda: [o for o in _env("CORS_ORIGINS", "").split(",") if o])

    # GPS / tracking
    gps_interval_s: int = field(default_factory=lambda: _int("GPS_INTERVAL_SECONDS", 5))
    stale_after_s: int = field(default_factory=lambda: _int("GPS_STALE_AFTER_SECONDS", 45))
    offline_after_s: int = field(default_factory=lambda: _int("GPS_OFFLINE_AFTER_SECONDS", 180))
    low_accuracy_m: float = field(default_factory=lambda: _float("GPS_LOW_ACCURACY_METERS", 50))
    reject_accuracy_m: float = field(default_factory=lambda: _float("GPS_REJECT_ACCURACY_METERS", 200))
    max_bus_speed_mps: float = field(default_factory=lambda: _float("GPS_MAX_SPEED_MPS", 33))  # ~120 km/h
    max_clock_skew_s: int = field(default_factory=lambda: _int("GPS_MAX_CLOCK_SKEW_SECONDS", 60))
    gps_retention_days: int = field(default_factory=lambda: _int("GPS_RETENTION_DAYS", 30))
    delay_threshold_min: float = field(default_factory=lambda: _float("DELAY_THRESHOLD_MINUTES", 5))
    # Service area (Lahore). Points outside are rejected.
    area_min_lat: float = field(default_factory=lambda: _float("AREA_MIN_LAT", 31.20))
    area_max_lat: float = field(default_factory=lambda: _float("AREA_MAX_LAT", 31.80))
    area_min_lon: float = field(default_factory=lambda: _float("AREA_MIN_LON", 74.00))
    area_max_lon: float = field(default_factory=lambda: _float("AREA_MAX_LON", 74.60))

    # Simulator (DEMO mode only)
    sim_interval_s: float = field(default_factory=lambda: _float("SIM_INTERVAL_SECONDS", 5))
    sim_time_scale: float = field(default_factory=lambda: _float("SIM_TIME_SCALE", 1.0))

    # Notifications (Firebase Cloud Messaging HTTP v1)
    fcm_project_id: str | None = field(default_factory=lambda: _env("FCM_PROJECT_ID"))
    fcm_service_account_file: str | None = field(default_factory=lambda: _env("FCM_SERVICE_ACCOUNT_FILE"))

    # Bootstrap admin (created on first start if no admin exists)
    bootstrap_admin_email: str | None = field(default_factory=lambda: _env("BOOTSTRAP_ADMIN_EMAIL"))
    bootstrap_admin_password: str | None = field(default_factory=lambda: _env("BOOTSTRAP_ADMIN_PASSWORD"))

    rate_limit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 300))
    auth_rate_limit_per_min: int = field(default_factory=lambda: _int("AUTH_RATE_LIMIT_PER_MINUTE", 20))
    web_dir: str = field(default_factory=lambda: _env("WEB_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "web", "public")))

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    @property
    def fcm_configured(self) -> bool:
        return bool(self.fcm_project_id and self.fcm_service_account_file and os.path.exists(self.fcm_service_account_file))

    def validate(self) -> None:
        if self.mode not in ("demo", "live"):
            raise RuntimeError("SPEEDO_MODE must be 'demo' or 'live'")
        if not self.jwt_secret:
            if self.env == "production":
                raise RuntimeError("JWT_SECRET must be set in production")
            self.jwt_secret = secrets.token_urlsafe(48)
            log.warning("JWT_SECRET not set: generated a temporary secret (tokens reset on restart)")
        elif len(self.jwt_secret) < 32 and self.env == "production":
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")


settings = Settings()
