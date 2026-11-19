from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Values come from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Speedo Live API"
    environment: str = "development"

    # Firebase: Firestore is the database, Firebase Authentication holds the accounts (see app/firebase.py)
    firebase_project_id: str | None = None
    firebase_credentials_file: str | None = None  # service-account JSON file
    firebase_credentials_json: str | None = None  # or its content (for hosts without a file system)
    firebase_web_api_key: str | None = None  # Project settings > General > Web API key
    firebase_storage_bucket: str | None = None  # e.g. my-project.firebasestorage.app (optional)

    redis_url: str | None = None  # optional: shares live WebSocket events between API instances

    cors_origins: str = "*"

    # demo  = simulated buses on clearly labeled DEMO routes
    # driver = positions come only from authorised driver apps
    # provider = positions come from an approved external GPS provider (see services/gps_provider.py)
    data_source: str = "driver"
    simulator_tick_seconds: float = 3.0

    gps_min_interval_seconds: int = 2
    gps_max_accuracy_m: float = 100.0
    gps_max_future_skew_seconds: int = 30
    gps_max_backfill_seconds: int = 3600
    gps_store_min_distance_m: float = 15.0
    gps_store_min_seconds: int = 30
    gps_retention_days: int = 30

    stale_after_seconds: int = 60
    offline_after_seconds: int = 300
    interrupt_trip_after_seconds: int = 1800
    delay_threshold_minutes: float = 5.0
    stopped_speed_mps: float = 0.8

    default_bus_speed_kmh: float = 20.0
    walk_speed_kmh: float = 4.5
    max_walk_m: float = 1500.0

    # Service area bounding box (Lahore district, generous margin)
    area_min_lat: float = 31.20
    area_max_lat: float = 31.75
    area_min_lng: float = 74.00
    area_max_lng: float = 74.65

    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"

    run_background_tasks: bool = True
    web_dist: str | None = None  # path to the exported web app to serve at "/"

    @field_validator("redis_url", "firebase_credentials_file", "firebase_credentials_json", "firebase_web_api_key",
                     "firebase_storage_bucket", "firebase_project_id")
    @classmethod
    def _empty_is_none(cls, v: str | None) -> str | None:
        return v.strip() if v and v.strip() else None

    @property
    def is_demo(self) -> bool:
        return self.data_source == "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
