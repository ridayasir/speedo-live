# Speedo Live — testing report

Test run: 4 November 2026, in the build workspace (Linux, Python 3.13, PostgreSQL 16 server, headless Chrome).

## Summary

| Area | How it was tested | Result |
|---|---|---|
| Backend API, GPS pipeline, ETA, permissions | `pytest` — 57 unit + integration tests against the real ASGI app on a live port | **57 passed** (3 consecutive runs, no flakes) |
| Web apps (passenger, admin, driver) | `web/tests/ui_flows.py` — Playwright in headless Chrome, clicking through real flows | **19/19 checks passed**, no JavaScript errors |
| PostgreSQL schema | `001_schema.sql` applied to a real PostgreSQL 16 server | **20 tables created** |
| PostgreSQL query compatibility | Every distinct SQL statement executed during the test run (155) was `PREPARE`d on PostgreSQL 16 | **155/155 valid** |
| Live (real-world) mode | Started with `SPEEDO_MODE=live` + bootstrap admin | No demo data, no simulator, admin login works |
| Responsive layout | Screenshots at 1440×900 and 390×844 (phone) | See `docs/screenshots/` |

## Backend test coverage (`backend/tests`)

**Registration, login and logout** (`test_auth.py`): email and Pakistani mobile sign-up (number normalised `+923…` → `03…`), validation errors, duplicate accounts, wrong password, token revocation on logout, scrypt password hashes, login rate limiting (429).

**Route and stop search, journeys, timetable** (`test_public.py`): DEMO labelling on every sample route/bus, ordered stops and chainage, text and nearby stop search, direct journeys, reverse direction, one-transfer journeys, "no stop within walking distance", same-place rejection, timetable for a date (and no service on Sunday for DEMO-3), live vs scheduled arrival labels, no driver data on public endpoints, OpenAPI document.

**Driver flow and GPS** (`test_driver_tracking.py`):
- driver sees assigned bus/route; passengers get 403 on driver endpoints; unauthenticated 401
- driver with no bus → `no_bus_assigned`; consent required before a trip (412); restart resumes the same trip
- GPS updates move the bus and produce a next stop + ETA
- **invalid coordinates** (lat 95 → 422; Karachi → `outside_service_area`; timestamp without timezone → 422)
- future timestamps, accuracy > 200 m, duplicates and impossible jumps are rejected; 50–200 m accuracy is stored but flagged
- offline queue flush: out-of-order batch with a duplicate → newest fix wins
- **ETA** decreases as the bus approaches, using observed speed
- **stale/offline detection**: 60 s without GPS → `stale`, 400 s → `offline`, and no live ETA is shown from stale data
- a stopped bus with fresh GPS stays `active` (not confused with lost GPS)
- **live map sync**: the SSE stream sends a snapshot, then pushes the bus update after a driver post
- admin stream needs a valid ticket and includes driver details; public stream does not
- trip end stops further posts; trip history; driver logout and consent withdrawal interrupt the active trip

**Admin** (`test_admin.py`): role checks (401/403), fleet view, full CRUD for stops/routes/buses/drivers/schedules with conflict rules (duplicate codes, a driver on two buses, deleting a stop still on a route), deactivated drivers can't sign in, bus maintenance hides its position, alerts notify followers, CSV import (dry-run, rejection of out-of-area rows, apply + verified source + schedule), daily report JSON and CSV, settings.

**Units** (`test_units.py`): haversine, polyline snapping (including routes that double back), ETA speed fallback, notification de-duplication and preferences, **"bus approaching" notification** from a stop watch (sent once), favourites/history/device tokens, GPS-provider adapter, simulator movement, GPS retention purge.

## UI flows (`web/tests/ui_flows.py`)

Passenger: live counters, stop autocomplete → journey plan, register, favourite a stop, set an arrival alert, favourites page, timetable, route detail. Admin: sign in, overview, live fleet over the admin stream, add a bus, route editor, reports, publish an alert, settings. Driver (phone viewport with simulated geolocation): sign in, consent, start trip, GPS fixes sent, end trip, trip history.

## What could not be tested here

- **Android apps** — the Expo projects were written and syntax-checked, but this workspace can't install npm packages or run an Android emulator, so they were not built or run. Follow `mobile/README.md` and test on a device.
- **WebSocket endpoint** (`/ws/live`) — needs `uvicorn[standard]`, which couldn't be installed here. The same hub feeds the SSE stream, which is tested.
- **Leaflet street map** — the CDN was unreachable here, so screenshots show the built-in fallback map. In a normal browser the OpenStreetMap street map loads.
- **PostgreSQL at runtime** — no Python Postgres driver could be installed. The schema and every query were checked on PostgreSQL 16 (above), but the app itself ran on SQLite. **PostGIS** isn't installed on that server; `002_postgis.sql` is untested.
- **Firebase push** — no FCM project/credentials. Notifications are stored and shown in the in-app inbox; push delivery code is in place but unverified.
- **Redis** — the built-in RESP client was not exercised against a server in the test suite (falls back to memory).

## Running the tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q
# UI flows (server running on :8000, Playwright installed):
python web/tests/ui_flows.py /tmp/speedo-shots
```
