# Speedo Live

**Your Bus, Your Route, Your Time.** Live Speedo bus tracking and route navigation for Lahore.

| Part | Folder | Stack |
|---|---|---|
| Backend API + real-time feed | `backend/` | Python FastAPI, Firebase (Cloud Firestore, Authentication, Storage, Cloud Messaging), WebSockets |
| Passenger web app + Admin dashboard | `web/` | Next.js 15 (static export), TypeScript, Tailwind, Leaflet + OpenStreetMap |
| Passenger Android app | `mobile/passenger/` | React Native + Expo SDK 52, Leaflet map in a WebView, FCM push |
| Driver Android app | `mobile/driver/` | React Native + Expo SDK 52, background GPS (foreground service) |

> All data lives in your **Firebase project**. A new project starts empty: load verified PMA/PTC routes through
> **Admin → Routes → Import CSV / Excel**, then add buses and drivers in the admin dashboard.

---

## 1. Firebase setup (once)

The database is **Cloud Firestore** and accounts are **Firebase Authentication** users; **Firebase Storage** keeps a
copy of every imported route file and **Cloud Messaging** sends push notifications. All of it uses one Firebase project.

1. Create a project at <https://console.firebase.google.com>.
2. **Build → Firestore Database → Create database** (production mode; pick a region near Pakistan, e.g. `asia-south1`).
3. **Build → Authentication → Get started → Sign-in method → Email/Password → Enable.**
4. Optional: **Build → Storage → Get started** (keeps imported route files). Note the bucket name, e.g. `your-project.firebasestorage.app`.
5. **Project settings → General**: copy the *Project ID* and the *Web API key*.
6. **Project settings → Service accounts → Generate new private key**. Save the file as
   `backend/firebase-service-account.json` (git-ignored; never commit it).
7. Fill in `backend/.env` (copy `backend/.env.example`):

   ```
   FIREBASE_PROJECT_ID=your-project-id
   FIREBASE_WEB_API_KEY=AIza...
   FIREBASE_CREDENTIALS_FILE=firebase-service-account.json
   FIREBASE_STORAGE_BUCKET=your-project.firebasestorage.app
   ```

8. Check the connection and create the first administrator:

   ```bash
   cd backend
   python -m app.firebase_check          # Firestore, Auth, Storage and FCM, each PASS or FAIL
   python -m app.seed --admin-email you@example.com --admin-password "a-long-password" --admin-name "Your Name"
   ```

9. Optional, with the [Firebase CLI](https://firebase.google.com/docs/cli): `firebase use --add` then
   `firebase deploy --only firestore:rules,storage` to deploy the deny-all rules in `firestore.rules` / `storage.rules`.
   Apps never talk to Firestore or Storage directly; only the API does, through the Admin SDK.

No composite indexes are needed: the API only sends single-field queries to Firestore.

> **No demo data.** A new project starts empty. Load the verified PMA/PTC routes, stops and timetables through
> **Admin → Routes → Import CSV / Excel**, then add buses and drivers in the admin dashboard.
> (`python -m app.seed --demo` loads clearly labelled sample data; it exists for the automated tests only.)

## 2. Running locally

**Requirements:** Python 3.12+, Node 20+, and the Firebase project from section 1. Redis is optional (only for
running more than one API process).

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload                       # http://localhost:8000/docs

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

On Windows, after the first-time setup, `start.bat` starts the API and the website and opens the browser.

Or in a container: `docker compose up --build` (reads `backend/.env` and mounts
`backend/firebase-service-account.json`), then open <http://localhost:8000>.

Open the Android apps on a phone with a **development build** (`npx expo run:android`) or on an emulator. The default API
URL `http://10.0.2.2:8000` reaches the host machine from the Android emulator. The driver app's background
location needs a development or production build; Expo Go does not support it.

**Sign-in.** The API signs users in with Firebase Authentication and returns a Firebase **ID token** (valid 1 hour)
plus a **refresh token**; the web and Android apps renew the ID token automatically. Users can sign in with their email
or their phone number. Accounts registered with a phone number only get an internal sign-in address
`<number>@phone.speedolive.invalid` in Firebase, because Firebase passwords need an email. Users created by hand in the
Firebase console can sign in too and get a passenger profile on first login.

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

**Push notifications (Firebase Cloud Messaging):** in the same Firebase project, add an Android app with package
`pk.speedolive.passenger` and download `google-services.json` into `mobile/passenger/` before building. The API sends
pushes with the service account it already uses for Firestore; nothing else to configure. Without
`google-services.json`, notifications still appear in the in-app inbox; they are just not pushed to the phone.

## 4. Deploying to the cloud

The root `Dockerfile` builds one container that serves the API, WebSocket feed and website on a single port.

**Render (blueprint included):** push this repo to GitHub, then in Render choose *New → Blueprint* and pick the repo.
`render.yaml` creates the web service; enter the `FIREBASE_*` values when asked (paste the service-account file's
JSON into `FIREBASE_CREDENTIALS_JSON`). Then create the first admin from the service's Shell with `python -m app.seed --admin-email ...`.

**Any other container host** (Railway, Fly.io, Google Cloud Run, a VPS): run the image with these environment variables:

| Variable | Required | Notes |
|---|---|---|
| `FIREBASE_PROJECT_ID` | yes | the Firebase project id |
| `FIREBASE_WEB_API_KEY` | yes | Project settings → General → Web API key (used to sign users in) |
| `FIREBASE_CREDENTIALS_JSON` or `FIREBASE_CREDENTIALS_FILE` | yes* | service-account key (content or path). *Not needed on Google Cloud, which uses the runtime's service account |
| `FIREBASE_STORAGE_BUCKET` | | keeps a copy of imported route files |
| `ENVIRONMENT` | yes | `production` |
| `DATA_SOURCE` | | `driver` (default), `provider` or `demo` |
| `CORS_ORIGINS` | | comma-separated origins if the website is hosted elsewhere |
| `REDIS_URL` | | shares live WebSocket events between API processes |

Run **one API instance**: the API keeps an in-memory mirror of the Firestore reference data (routes, stops, buses,
users, active trips) for fast ETA and planning, and that mirror is not shared between instances.

HTTPS: every host above terminates HTTPS for you. **Backups:** enable Firestore's scheduled backups or
point-in-time recovery (Firestore → Disaster recovery), or export with
`gcloud firestore export gs://<bucket>/backups/$(date +%F)` from a daily job.

To host the website separately (Vercel, Netlify, Cloudflare Pages): build `web/` with
`NEXT_PUBLIC_API_URL=https://your-api-host` and upload `web/out/`.

## 5. Demo mode and real-world mode

| `DATA_SOURCE` | Where bus positions come from |
|---|---|
| `driver` (default) | Only authorised driver apps. |
| `demo` | The built-in simulator also moves buses flagged `is_demo` along DEMO routes (tests and demonstrations only). |
| `provider` | An approved external GPS feed, via `backend/app/services/gps_provider.py` (match buses by *GPS device ID*). |

Going live: import verified routes and add real buses and drivers in the admin dashboard.
No government system is accessed without authorisation; the provider adapter is an empty interface until one is approved.

## 6. How live tracking works

```
Driver app (GPS every 5 s, foreground service, offline queue)
   → POST /api/driver/trips/{id}/locations        (Firebase ID token, driver must own the bus and the active trip)
   → validate: coordinates, Lahore service area, timestamp, accuracy ≤ 100 m, speed and jump plausibility, duplicates
   → Firestore (thinned history in gps_locations: a point every 15 m or 30 s) + latest position on the bus
   → WebSocket /ws/live (Redis pub/sub when several processes) → passenger web and Android apps
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

* Passwords are held only by Firebase Authentication; the API verifies Firebase ID tokens with the Admin SDK and
  applies role-based access (passenger / driver / admin, stored on the Firestore profile) on every endpoint.
  Deactivating a driver also disables their Firebase account.
* Firestore and Storage security rules deny all direct client access; only the API (Admin SDK) reads and writes.
* Drivers can only post GPS for the bus assigned to them and only during a trip they started with explicit consent.
* Public endpoints never return driver names, phone numbers or licence numbers (covered by a test).
* Input validation with Pydantic; rate limiting (120 req/min per IP, 10/min on login and registration).
* GPS history is deleted after `GPS_RETENTION_DAYS` (30 by default). Admin actions are recorded in an audit log.
* Secrets only come from environment variables; `.env` files and service-account keys are git-ignored.

## 9. Tests

```bash
cd backend && pytest -q                   # in-memory Firestore/Auth fakes; no Firebase project needed
python -m app.firebase_check              # live check against the Firebase project in backend/.env
```

See [TESTING.md](TESTING.md) for what is covered and what has not been tested yet.

## 10. Project layout

```
backend/app/
  main.py               app, background loops (simulator, stale detection, alerts, retention)
  firebase.py           Firebase Admin SDK: Firestore, Auth, Storage, FCM   firebase_check.py  live connection check
  store.py              Firestore persistence (unit of work, in-memory mirror)  models.py  Firestore documents
  routers/              auth, public (passenger), me, driver, admin, ws
  services/tracking.py  GPS ingestion, status, ETA          services/planner.py  journey planning
  services/simulator.py DEMO buses                          services/gps_provider.py  real GPS adapter
  services/importer.py  CSV/XLSX import                     services/notifications.py FCM
  services/accounts.py  Firebase Authentication accounts
firebase.json, firestore.rules, storage.rules   Firebase CLI config and security rules
web/src/app/            pages: / live routes route stop timetable favorites profile admin
mobile/passenger/       Expo passenger app                  mobile/driver/  Expo driver app
docs/openapi.json       API specification
```
