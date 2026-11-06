import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://speedo:speedo@localhost:5432/speedo_test")
os.environ["RUN_BACKGROUND_TASKS"] = "false"
os.environ["REDIS_URL"] = ""
os.environ["RATE_LIMIT_AUTH"] = "1000/minute"
os.environ["RATE_LIMIT_DEFAULT"] = "10000/minute"
os.environ["DATA_SOURCE"] = "demo"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine, is_sqlite  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services import tracking  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    if not is_sqlite:
        with engine.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


@pytest.fixture()
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, ident, pw):
    r = client.post("/api/auth/login", json={"identifier": ident, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_h(client):
    return login(client, "admin@speedolive.demo", "Admin@12345")


@pytest.fixture(scope="session")
def driver_h(client):
    return login(client, "driver@speedolive.demo", "Driver@12345")


@pytest.fixture(scope="session")
def passenger_h(client):
    return login(client, "passenger@speedolive.demo", "Passenger@123")


@pytest.fixture(autouse=True)
def _clear_caches():
    tracking._route_cache.clear()
    tracking._recent.clear()
    yield
