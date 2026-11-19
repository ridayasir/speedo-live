"""Load pma_routes_import.csv into the Firebase project (same code path as Admin > Routes > Import).

    cd backend
    .venv\\Scripts\\python ..\\data\\pma\\import_to_app.py

Restart the API afterwards so it picks up the new routes.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app import firebase  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services import importer  # noqa: E402

SOURCE = ("PMA website (pma.punjab.gov.pk) feeder route pages, stop order retrieved 2026-11-19; "
          "stop positions approximate (OpenStreetMap)")

firebase.init()
data = (HERE / "pma_routes_import.csv").read_bytes()
with SessionLocal() as db:
    rep = importer.import_routes(db, importer.read_table("pma_routes_import.csv", data), SOURCE[:255])
    if rep.errors:
        print("ERRORS:", *rep.errors[:20], sep="\n  ")
        raise SystemExit(1)
    stored = firebase.files.upload("imports/pma_routes_import_2026-11-19.csv", data, "text/csv")
print({k: v for k, v in rep.__dict__.items() if k != "errors"}, "| file copy:", stored or "Storage not configured")
