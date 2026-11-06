# Speedo Live

**Your Bus, Your Route, Your Time.** Live Speedo bus tracking and route navigation for Lahore.

| Part | Folder | Stack |
|---|---|---|
| Backend API + real-time feed | `backend/` | Python FastAPI, PostgreSQL + PostGIS, Redis, WebSockets, JWT |
| Passenger web app + Admin dashboard | `web/` | Next.js 15 (static export), TypeScript, Tailwind, Leaflet + OpenStreetMap |
| Passenger Android app | `mobile/passenger/` | React Native + Expo SDK 52, Leaflet map in a WebView, FCM push |
| Driver Android app | `mobile/driver/` | React Native + Expo SDK 52, background GPS (foreground service) |

> **DEMO MODE.** The project ships with *demonstration* data only: 8 sample routes, 20 stops at approximate
> Lahore landmark positions and 16 simulated buses, all flagged `is_demo` and labeled **DEMO** in every app.
> These are **not** official Speedo routes, bus numbers or timetables. Load verified PMA/PTC data through
> **Admin → Routes → Import CSV / Excel** before any public use.

---

## 1. Quick start (Docker, everything in one command)

```bash
docker compose up --build
# open http://localhost:8000          passenger web app
#      http://localhost:8000/admin/   admin dashboard
#      http://localhost:8000/docs     API documentation (Swagger)
```

Demo accounts (created by the seed; change the passwords with `SEED_*_PASSWORD` env vars):

| Role | Login | Password |
|---|---|---|
| Admin | `admin@speedolive.demo` | `Admin@12345` |
| Driver | `driver@speedolive.demo` or `+923000000001` | `Driver@12345` |
| Passenger | `passenger@speedolive.demo` | `Passenger@123` |

The demo driver is assigned bus **DRV-001** (not simulated), so you can drive it with the driver app.

## 2. Running the parts separately (development)

**Requirements:** Python 3.12+, Node 20+, PostgreSQL 16 with PostGIS 3, Redis 7 (optional; without it, live updates work within one API process).

```bash
# database
createuser -s speedo; createdb -O speedo speedo
psql speedo -c "ALTER USER speedo PASSWORD 'speedo'"

# backend
cd backend
cp .env.example .env            # set JWT_SECRET etc.
pip install -r requirements-dev.txt
alembic upgrade head            # schema + PostGIS extension
python -m app.seed              # DEMO data and demo accounts
uvicorn app.main:app --reload   # http://localhost:8000/docs

# web
cd web
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                     # http://localhost:3000  (admin at /admin/)

# Android apps (Expo)
cd mobile/passenger             # or mobile/driver
npm install
EXPO_PUBLIC_API_URL=http://<your-computer-LAN-IP>:8000 npx expo start
```

Open the app on a phone with a **development build** (`npx expo run:android`) or on an emulator. The default API
URL `http://10.0.2.2:8000` reaches the host machine from the Android emulator. The driver app's background
location needs a development or production build; Expo Go does not support it.

### Local mode without Postgres or Docker (Windows)

For trying the app on one machine, the backend can run on SQLite. Set `DATABASE_URL=sqlite:///./speedo_local.db`
and `REDIS_URL=` in `backend/.env`, create `backend/.venv` and install `requirements-dev.txt`, run `npm install` in
`web/`, then double-click `start.bat`. Tables are created by `python -m app.seed` (Alembic is not used here).
Nearby-stop search uses plain lat/lng instead of PostGIS. This mode is for local development only; production uses PostGIS.

## 3. Building the Android apps

Using EAS (Expo's build service, free tier available):

```bash
npm install -g eas-cli
eas login
cd mobile/passenger
# set your API host in eas.json (EXPO_PUBLIC_API_URL) first
eas build -p android --profile preview      # installable .apk
eas build -p android --profile production   # .aab for Google Play
```

Repeat in `mobile/driver`. To build locally instead: `npx expo prebuild -p android && cd android && ./gradlew assembleRelease`
(needs Android Studio / SDK 34).

**Push notifications (Firebase Cloud Messaging):**
1. Create a Firebase project, add an Android app with package `pk.speedolive.passenger`, download `google-services.json` into `mobile/passenger/`.
2. Create a service-account key (Project settings → Service accounts) and give the API `FCM_PROJECT_ID` and `FCM_CREDENTIALS_FILE`.
Without these, notifications are still created and appear in the in-app inbox; they are just not pushed to the phone.

## 4. Deploying to the cloud

The root `Dockerfile` builds one container that serves the API, WebSocket feed and website on a single port.

**Render (blueprint included):** push this repo to GitHub, then in Render choose *New → Blueprint* and pick the repo.
`render.yaml` creates the web service, a PostgreSQL database and Redis. Set `SEED_ADMIN_PASSWORD` when prompted.
Render's Postgres supports PostGIS; the first migration runs `CREATE EXTENSION postgis`.

**Any other container host** (Railway, Fly.io, Google Cloud Run, a VPS): run the image with these environment variables:

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL with PostGIS. `postgres://` URLs are accepted. |
| `JWT_SECRET` | yes | long random string; the app refuses to start in production with the default |
| `ENVIRONMENT` | yes | `production` |
| `REDIS_URL` | recommended | needed when running more than one instance |
| `DATA_SOURCE` | | `demo` (default), `driver` or `provider` |
| `CORS_ORIGINS` | | comma-separated origins if the website is hosted elsewhere |
| `FCM_PROJECT_ID`, `FCM_CREDENTIALS_FILE` | | push notifications |
| `SEED_ADMIN_PASSWORD` etc. | | passwords for seeded accounts |

HTTPS: every host above terminates HTTPS for you. **Backups:** enable your database provider's automated daily
backups (Render, Railway, Cloud SQL and Neon all offer them); for a self-hosted database run
`pg_dump -Fc "$DATABASE_URL" > speedo-$(date +%F).dump` daily from cron.

To host the website separately (Vercel, Netlify, Cloudflare Pages): build `web/` with
`NEXT_PUBLIC_API_URL=https://your-api-host` and upload `web/out/`.

## 5. Demo mode and real-world mode

| `DATA_SOURCE` | Where bus positions come from |
|---|---|
| `demo` | The built-in simulator moves buses flagged `is_demo` along DEMO routes. Driver apps work too. |
| `driver` | Only authorised driver apps. The simulator is off. |
| `provider` | An approved external GPS feed, via `backend/app/services/gps_provider.py` (match buses by *GPS device ID*). |

Going live: import verified routes, add real buses and drivers in the admin dashboard, delete the demo
data (`python -m app.seed --reset` removes demo routes, stops and buses), then set `DATA_SOURCE=driver` or `provider`.
No government system is accessed without authorisation; the provider adapter is an empty interface until one is approved.

## 6. How live tracking works

```
Driver app (GPS every 5 s, foreground service, offline queue)
   → POST /api/driver/trips/{id}/locations        (JWT, driver must own the bus and the active trip)
   → validate: coordinates, Lahore service area, timestamp, accuracy ≤ 100 m, speed and jump plausibility, duplicates
   → PostgreSQL/PostGIS (thinned history: a point every 15 m or 30 s) + latest position on the bus
   → Redis pub/sub → WebSocket /ws/live → passenger web and Android apps
```

* **Stale vs stopped:** a bus with no update for 60 s is *GPS signal lost* (stale) and after 5 min *offline*. A bus
  sending updates at speed < 0.8 m/s is *stopped*. These are never confused. A trip with no updates for 30 min is
  marked *interrupted*.
* **ETA:** the bus is snapped to the route line; remaining distance ÷ a blend of recent movement and the route's
  historical speed (learned from completed trips), plus ~20 s per intermediate stop. A traffic hook
  (`traffic_factor`) is ready for a traffic feed. Without fresh GPS, only **scheduled** times are shown, labeled as such.
* **Delays:** compared with the route's scheduled stop offsets from the trip start. Followers of the route get one delay notification per trip.

## 7. Route data import format

Download templates from Admin → Routes → Import. `routes.csv` (one row per stop, in order):

```
route_code,route_name,sequence,stop_code,stop_name,lat,lng,offset_minutes,is_major,color,stop_name_ur
```

`schedules.csv`: `route_code,days,first_departure,last_departure,frequency_minutes,notes` (days like `mon,tue,wed`).
Optional `shapes.csv` (`route_code,sequence,lat,lng`) gives the road geometry; without it, lines run straight between stops.
Every import must state its source, which is stored on each route and stop.

## 8. Security and privacy

* bcrypt password hashing, JWT bearer tokens, role-based access (passenger / driver / admin) on every endpoint.
* Drivers can only post GPS for the bus assigned to them and only during a trip they started with explicit consent.
* Public endpoints never return driver names, phone numbers or licence numbers (covered by a test).
* Input validation with Pydantic; rate limiting (120 req/min per IP, 10/min on login and registration).
* GPS history is deleted after `GPS_RETENTION_DAYS` (30 by default). Admin actions are recorded in an audit log.
* Secrets only come from environment variables; `.env` files are git-ignored.

## 9. Tests

```bash
cd backend && createdb -O speedo speedo_test && pytest -q
```

See [TESTING.md](TESTING.md) for what is covered and what has not been tested yet.

## 10. Project layout

```
backend/app/
  main.py               app, background loops (simulator, stale detection, alerts, retention)
  models.py             SQLAlchemy models (18 tables)        migrations/  Alembic
  routers/              auth, public (passenger), me, driver, admin, ws
  services/tracking.py  GPS ingestion, status, ETA          services/planner.py  journey planning
  services/simulator.py DEMO buses                          services/gps_provider.py  real GPS adapter
  services/importer.py  CSV/XLSX import                     services/notifications.py FCM
web/src/app/            pages: / live routes route stop timetable favorites profile admin
mobile/passenger/       Expo passenger app                  mobile/driver/  Expo driver app
docs/openapi.json       API specification
```
