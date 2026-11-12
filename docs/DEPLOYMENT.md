# Deploying Speedo Live

Status: **not deployed.** The build workspace had no access to any cloud host or package registry, so nothing is running publicly yet. Everything below is ready to use.

## 1. Run locally (5 minutes)

Needs Python 3.10+.

```bash
./run.sh                      # creates a venv, installs requirements, starts on :8000
```

Open http://localhost:8000 (passenger), http://localhost:8000/admin, http://localhost:8000/driver, http://localhost:8000/docs (API).
Demo accounts (password `Demo@12345`): `passenger@speedo.demo`, `admin@speedo.demo`, `driver@speedo.demo` (phone `03000000001`).

The compiled web app is already in `web/public/js`. To rebuild after editing `web/src`: `cd web && npm install && npm run build`.

## 2. Docker (API + web + PostgreSQL/PostGIS + Redis)

```bash
cd deploy
cp ../.env.example .env        # set JWT_SECRET, POSTGRES_PASSWORD, BOOTSTRAP_ADMIN_*
docker compose up --build
```

Migrations run automatically on start (`001_schema`, then `002_postgis` because `ENABLE_POSTGIS=true`).

## 3. Cloud

Any host that runs a Docker image works. The image serves the API and the web apps on `$PORT`.

**Render (free)** — `render.yaml` (repo root) is a blueprint for a free web service in Singapore; it asks for `DATABASE_URL`, for which use a free Postgres from neon.tech (free forever, unlike Render’s 30-day free database), `JWT_SECRET` generated, HTTPS automatic, redeploys on every push. In Render: New → Blueprint → select the repo → Apply. Demo accounts (`admin@speedo.demo` / `Demo@12345`) are created automatically; add `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` in the service settings for your own admin.

**Railway / Fly.io / Google Cloud Run / Azure Container Apps** — deploy `deploy/Dockerfile`, attach a managed PostgreSQL (enable the PostGIS extension if offered), and set:

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (refuses to start without a strong `JWT_SECRET`, enables HSTS) |
| `JWT_SECRET` | 48+ random characters |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/speedo` |
| `ENABLE_POSTGIS` | `true` if the extension is available |
| `REDIS_URL` | optional |
| `TRUST_PROXY` | `true` behind the host's load balancer |
| `SPEEDO_MODE` | `demo` until real data and drivers are ready, then `live` |
| `BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | first administrator |

HTTPS is provided by the host. If the web app is served from a different domain than the API, set `CORS_ORIGINS` and add `<script>window.SPEEDO_API_BASE="https://api.example"</script>` before the app script in the HTML files.

**Scaling past one instance:** the live-update hub is in-process. Run a single API instance (it handles thousands of SSE clients), or add Redis pub/sub between instances in `app/realtime.py` before scaling horizontally.

**Map tiles:** the default uses tile.openstreetmap.org, which is fine for testing but not for heavy production traffic. Use a tile provider (MapTiler, Stadia, Thunderforest, or self-hosted) and change `map.tiles` in `/api/config` (`app/api/public.py`).

**Backups:** enable automated daily backups on the managed Postgres. GPS points older than `GPS_RETENTION_DAYS` (default 30) are deleted hourly.

## 4. Android apps

See `mobile/README.md`. Short version:

```bash
cd mobile/passenger            # or mobile/driver
npm install && npx expo install --fix
EXPO_PUBLIC_API_URL=https://your-api-host npx eas build -p android --profile preview   # APK
```

## 5. Switching from DEMO to real-world mode

1. Import verified routes (Admin → Routes → Import CSV/Excel), marking the official source.
2. Add real buses and drivers; drivers install the driver app and accept location consent.
3. Set the DEMO routes to inactive (or start from an empty database).
4. Set `SPEEDO_MODE=live`. The simulator stops and no demo data is seeded.
5. For on-board trackers instead of phones: `GPS_SOURCE=provider`, `GPS_PROVIDER_URL`, `GPS_PROVIDER_TOKEN`, and set each bus's GPS device ID. Adapt `fetch()` in `app/services/provider.py` to the provider's format. Only connect feeds you are authorised to use.
