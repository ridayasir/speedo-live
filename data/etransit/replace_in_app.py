"""Replace the earlier PMA-website routes (codes FRT*, stops PMA-*) with the e-Transit Speedo network.

    cd backend
    .venv\\Scripts\\python ..\\data\\etransit\\replace_in_app.py

Stop the API first and start it again afterwards (it keeps an in-memory copy of the data).
Run `python -m app.demo_fleet --remove` before and `python -m app.demo_fleet` after, so the demo
buses move to the new routes.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app import firebase  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import BusStop, Route  # noqa: E402
from app.services import importer  # noqa: E402

SOURCE = "PMA e-Transit route planner, line 42 LFR- Speedo (etransit.punjab.gov.pk), downloaded 2026-11-20"

firebase.init()
with SessionLocal() as db:
    old_routes = [r for r in db.all(Route) if r.code.startswith("FRT")]
    for r in old_routes:
        db.delete(r)
    db.commit()
    # Delete the old stops in one batch. Their references are cleared here with ONE read of the journey
    # history, instead of BusStop.on_delete's two Firestore queries per stop (too slow for hundreds of stops).
    from app.models import ArrivalWatch, FavoriteStop, Journey, ServiceAlert
    from app.store import store

    old_stops = [s for s in db.all(BusStop) if s.code.startswith("PMA-")]
    old_ids = {s.id for s in old_stops}
    for model in (FavoriteStop, ServiceAlert, ArrivalWatch):
        for x in db.all(model):
            if x.stop_id in old_ids:
                db.delete(x)
    for j in db.where(Journey):
        for field in ("from_stop_id", "to_stop_id"):
            if getattr(j, field) in old_ids:
                setattr(j, field, None)
    with store.lock:
        store.deleted.extend(old_stops)  # references handled above, so skip the per-stop cascade
    db.commit()
    print(f"removed {len(old_routes)} PMA-website routes and {len(old_stops)} of their stops")

    routes = (HERE / "speedo_routes.csv").read_bytes()
    schedules = (HERE / "speedo_schedules.csv").read_bytes()
    rep = importer.import_routes(db, importer.read_table("speedo_routes.csv", routes), SOURCE)
    if rep.errors:
        raise SystemExit("route errors:\n  " + "\n  ".join(rep.errors[:20]))
    srep = importer.import_schedules(db, importer.read_table("speedo_schedules.csv", schedules))
    if srep.errors:
        raise SystemExit("schedule errors:\n  " + "\n  ".join(srep.errors[:20]))
    for name, data in (("speedo_routes.csv", routes), ("speedo_schedules.csv", schedules)):
        firebase.files.upload(f"imports/etransit_2026-11-20_{name}", data, "text/csv")
    print({k: v for k, v in rep.__dict__.items() if k != "errors"}, "| timetables:", srep.schedules)
