# Speedo Live — backend API + web apps in one image.
# Build from the repository root:  docker build -f deploy/Dockerfile -t speedo-live .

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/tsconfig.json ./
RUN npm install --no-audit --no-fund
COPY web/src ./src
COPY web/public ./public
RUN npx tsc -p .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEB_DIR=/app/web
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=web /web/public /app/web
RUN useradd --create-home speedo && mkdir -p data && chown -R speedo /app
USER speedo
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
