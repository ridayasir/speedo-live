# Speedo Live — backend API + web apps in one image.
# Build:  docker build -t speedo-live .
# Works with zero configuration (e.g. Render "New Web Service" -> pick repo -> Free): demo mode,
# built-in SQLite, and a random JWT_SECRET per start if none is set. Override any of these with env vars.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/tsconfig.json ./
RUN npm install --no-audit --no-fund
COPY web/src ./src
COPY web/public ./public
RUN npx tsc -p .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEB_DIR=/app/web \
    APP_ENV=production SPEEDO_MODE=demo TRUST_PROXY=true ENABLE_POSTGIS=false
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=web /web/public /app/web
RUN useradd --create-home speedo && mkdir -p data && chown -R speedo /app
USER speedo
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'))"
CMD ["sh", "-c", "export JWT_SECRET=\"${JWT_SECRET:-$(python -c 'import secrets;print(secrets.token_urlsafe(48))')}\"; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
