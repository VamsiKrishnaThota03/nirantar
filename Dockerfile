# Nirantar — single image serving the API and the built dashboard.

# --- stage 1: build the dashboard -----------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
# Dev dependencies are needed for the typecheck and the Vite build.
RUN npm ci --no-audit --fund=false 2>/dev/null || npm install --no-audit --fund=false
COPY frontend/ ./
RUN npm run build


# --- stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim AS runtime

# Never run as root.
RUN useradd --create-home --uid 10001 nirantar

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
COPY LICENSE README.md SECURITY.md ./

# Writable location for the SQLite database and the ledger signing key.
RUN mkdir -p /app/var && chown -R nirantar:nirantar /app/var
USER nirantar

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    DB_PATH=/app/var/nirantar.sqlite3 \
    LEDGER_KEY_PATH=/app/var/ledger_signing_key.pem \
    DEMO_MODE=true

# A wildcard bind is correct *inside* a container: the boundary is the port
# publish, and the platform's own proxy has to be able to reach us. The
# application default remains 127.0.0.1 (see backend/nirantar/config.py), so
# running it outside a container never listens beyond loopback by accident.
# docker-compose.yml publishes this to 127.0.0.1 only.
ENV HOST=0.0.0.0

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=4s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=3).status==200 else 1)"

WORKDIR /app/backend
# --proxy-headers with a permissive forwarded-allow-ips is required for the
# app to see the real client address behind a platform load balancer whose IP
# we cannot know in advance. The consequence is that X-Forwarded-For is
# attacker-controllable, so the per-client demo rate limiter can be evaded by
# spoofing it. That limiter is documented as a spend guard rather than a
# security control (SECURITY.md); nothing security-relevant keys off the
# client address. If you put Nirantar behind a proxy with a known address,
# narrow this to that address.
CMD ["sh", "-c", "exec python -m uvicorn nirantar.main:app --host \"$HOST\" --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
