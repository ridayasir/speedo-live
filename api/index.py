"""Vercel entry point: the Speedo Live API (FastAPI) as one serverless Python function.

Vercel routes /api/* and /health here through a rewrite that passes the original path in ?__p=...;
this wrapper restores it before FastAPI sees the request. Serverless mode (SERVERLESS=1):
- Firebase connects on the first request of each instance (cold start) and loads the data mirror;
- no background loops: requests advance the bus simulator and run the monitors (app/services/on_request.py);
- WebSockets are not available, so the web app polls /api/buses/live instead.
Configure FIREBASE_PROJECT_ID, FIREBASE_WEB_API_KEY, FIREBASE_CREDENTIALS_JSON (and DATA_SOURCE) in the
Vercel project's environment variables.
"""
import os
import sys
from urllib.parse import parse_qsl, urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("SERVERLESS", "true")
os.environ.setdefault("ENVIRONMENT", "production")
os.environ.setdefault("REDIS_URL", "")

from app.main import app as speedo  # noqa: E402


async def app(scope, receive, send):
    if scope["type"] == "http":
        query = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
        original = next((v for k, v in query if k == "__p"), None)
        if original:
            rest = urlencode([(k, v) for k, v in query if k != "__p"])
            scope = dict(scope, path=original, raw_path=original.encode(), query_string=rest.encode())
    elif scope["type"] == "lifespan":
        # Vercel may not send lifespan events; the app connects lazily on the first request anyway
        pass
    await speedo(scope, receive, send)
