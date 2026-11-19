# Single container: FastAPI API + exported Next.js web app on one port.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# empty = call the API on the same origin
ENV NEXT_PUBLIC_API_URL="" NEXT_TELEMETRY_DISABLED=1
RUN npx next build

FROM python:3.12-slim
WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEB_DIST=/app/web
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/out /app/web
EXPOSE 8000
# Firebase settings come from the environment (FIREBASE_PROJECT_ID, FIREBASE_WEB_API_KEY,
# FIREBASE_CREDENTIALS_JSON, FIREBASE_STORAGE_BUCKET). Create the first admin once with:
#   python -m app.seed --admin-email ... --admin-password ...
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
