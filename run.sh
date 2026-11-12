#!/usr/bin/env sh
# Run Speedo Live locally (DEMO mode, SQLite). Needs Python 3.10+ (and Node only to rebuild the web app).
set -e
cd "$(dirname "$0")"
if [ ! -d backend/.venv ]; then python3 -m venv backend/.venv; fi
. backend/.venv/bin/activate
pip install -q -r backend/requirements.txt
if command -v npx >/dev/null 2>&1 && [ -d web/src ]; then (cd web && npx -y -p typescript tsc -p .) || echo "web build skipped; using prebuilt web/public/js"; fi
cd backend
echo "Speedo Live: http://localhost:8000  (admin: /admin, driver: /driver, API docs: /docs)"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
