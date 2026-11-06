from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import get_settings


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """Timezone-aware UTC datetime. SQLite drops the offset, so restore it on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        return value.astimezone(timezone.utc) if value is not None and value.tzinfo else value

    def process_result_value(self, value: datetime | None, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None and not value.tzinfo else value


# PostgreSQL + PostGIS is the real database. SQLite is a zero-install mode for local development only.
is_sqlite = get_settings().database_url.startswith("sqlite")
engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {},
)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # simulator writes while API requests read
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
