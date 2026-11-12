# Speedo Live

**Your Bus, Your Route, Your Time.** Live Speedo bus tracking and route navigation for Lahore.

A passenger opens the app, picks a destination, sees which Speedo route to take and the nearest stop, watches the bus on the map and gets an arrival time. A driver starts a trip and shares the bus's GPS. An administrator manages buses, routes, stops, drivers, timetables and alerts, and watches the whole fleet live.

> **DEMO MODE by default.** The routes, buses, stops and timetables that ship with the app are sample data, not official Speedo information, and buses are moved by a simulator. Everything demo is labelled DEMO in the app. Load verified routes through Admin → Import before real use. See [docs/ROUTE_DATA.md](docs/ROUTE_DATA.md).

## Quick start

```bash
./run.sh            # Python 3.10+; installs requirements and starts on http://localhost:8000
```

| App | URL | Demo sign-in (password `Demo@12345`) |
|---|---|---|
| Passenger web app | http://localhost:8000 | `passenger@speedo.demo` (or browse without an account) |
| Admin dashboard | http://localhost:8000/admin | `admin@speedo.demo` |
| Driver web app | http://localhost:8000/driver | `driver@speedo.demo` / `03000000001` |
| API docs (Swagger) | http://localhost:8000/docs | |

## What's included

| Module | Where | Highlights |
|---|---|---|
| Backend API | `backend/app` | 70 REST endpoints, JWT auth with roles, SSE + WebSocket live feed, ETA engine, journey planner, timetables, notifications, reports, CSV/Excel import |
| Database | `backend/migrations` | PostgreSQL schema (20 tables, FKs, indexes), PostGIS geography columns + GiST indexes, SQLite for local dev |
| Passenger web | `web/src/passenger.ts` | Home with search, nearby stops, live status, popular/recent/favourite; Live Tracking; Routes; stop arrivals; journey planner; Timetable; Favorites; Profile with alerts inbox |
| Admin web | `web/src/admin.ts` | Overview, Buses, Routes (editor with stop ordering + map), Stops, Drivers, Live Fleet, Schedules, Alerts, Reports (CSV export), Settings |
| Driver web | `web/src/driver.ts` | Consent, start/end trip, GPS sharing with offline queue, GPS status, route, trip history |
| Passenger Android | `mobile/passenger` | Expo app: Home, Explore, Live Map, Favorites, Profile, FCM push |
| Driver Android | `mobile/driver` | Expo app with a background foreground-service location task and offline queue |
| Deployment | `deploy/` | Dockerfile, docker-compose (PostGIS + Redis), Render blueprint |
| Docs | `docs/` | [API](docs/API.md), [testing report](docs/TESTING.md), [deployment](docs/DEPLOYMENT.md), [route data](docs/ROUTE_DATA.md), [screenshots](docs/screenshots) |

## How it works

```
Driver app ──GPS every 5 s──▶ POST /api/driver/location(/batch)
                                   │ validate: driver ↔ assigned bus ↔ active trip,
                                   │ coordinates in Lahore area, timestamp, accuracy,
                                   │ duplicates, impossible jumps
                                   ▼
                         gps_locations + buses.last_* (+ Redis cache)
                                   │
                                   ▼  in-process hub
                 SSE /api/live/stream  ·  WebSocket /ws/live
                                   ▼
                    Passenger web / Android, Admin fleet map
```

**Status of each bus:** `active` (fresh GPS), `delayed` (≥ 5 min behind the timetable pace), `stale` (no fix for 45 s), `offline` (no fix for 3 min), `out_of_service`. A bus standing still at a stop with fresh GPS stays `active`; only missing GPS makes it stale.

**ETA:** the bus position is snapped onto the route geometry; remaining distance to the stop along the route is divided by a blended speed (recent observed speed from the last fixes, historical speed for that route/direction/hour, the route's average speed, and a traffic factor hook), plus dwell time at intermediate stops. If GPS is stale there is no live ETA; the app shows the timetable estimate and labels it **Scheduled**.

**Journey planner:** finds stops within 1.5 km walking of start and destination, then direct routes in the right direction, or one-transfer journeys through shared stops, ranked by total time including the live wait for the next bus.

**DEMO vs real-world mode:** `SPEEDO_MODE=demo` seeds labelled sample data and runs the simulator, which feeds positions through the same validation pipeline as a driver's phone (one bus runs slow to show delays, one drops GPS to show stale/offline). `SPEEDO_MODE=live` never seeds or simulates; positions come only from authorised drivers or an authorised GPS provider feed (`GPS_SOURCE=provider`).

## Security & privacy

scrypt password hashing · JWT with revocation on logout · role checks on every admin/driver endpoint · drivers can only post for their assigned bus during their own trip · pydantic validation on all input · global and per-endpoint rate limits · security headers (+HSTS in production) · no driver details on public endpoints · admin live stream uses short-lived tickets · recorded driver consent before any location sharing, withdrawable · GPS retention limit (30 days default) · secrets only from environment variables.

## Differences from the requested stack

The build workspace had no access to the npm or PyPI registries, so the app was built with what was installed:

| Requested | Delivered | Why / how to change |
|---|---|---|
| FastAPI | **Starlette** (the framework FastAPI runs on) + pydantic, with a hand-built OpenAPI/Swagger page | FastAPI wasn't installable. Handlers are small functions, so moving to FastAPI routers is mechanical. |
| React/Next.js + Tailwind | **TypeScript** compiled with `tsc`, no framework; hand-written CSS with the same design tokens | React/Next/Tailwind weren't installable. |
| PostgreSQL + PostGIS | PostgreSQL schema + PostGIS migration; **ran on SQLite** in the workspace | No Postgres driver was installable. Schema and all queries were checked on PostgreSQL 16 (see testing report). |
| WebSockets | **SSE** (tested) and a WebSocket endpoint (untested here) | WebSocket needs `uvicorn[standard]`, which is in `requirements.txt`. |
| Leaflet | Leaflet + OpenStreetMap in the browser, with a built-in offline fallback map | |
| React Native / Expo | As requested | Written but not built here. |

## Project layout

```
backend/   app/ (main, http, config, db, security, cache, realtime, geo, schemas, seed)
           app/api/ (account, public, driver, admin)   app/services/ (tracking, eta, planner,
           schedule, network, notify, simulator, provider, importer, reports)
           migrations/  seed/  tests/
web/       src/*.ts → public/js   public/{index,admin,driver}.html   tests/ui_flows.py
mobile/    passenger/  driver/
deploy/    Dockerfile  docker-compose.yml   (render.yaml is at the repo root)
docs/      API.md  TESTING.md  DEPLOYMENT.md  ROUTE_DATA.md  openapi.json  screenshots/
```

## Known gaps

- No official route data is included (by design); a real Speedo deployment needs PMA data and authorisation for any GPS feed.
- Phone OTP sign-in is not implemented (phone + password is); plug an SMS provider into `api/account.py` if needed.
- Android apps, WebSocket, PostGIS, FCM push and Redis are implemented but were not run in the build workspace. Details in [docs/TESTING.md](docs/TESTING.md).
