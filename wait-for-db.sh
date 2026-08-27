#!/bin/sh
set -e

echo "⏳ Waiting for Postgres to be ready..."
# Pure-stdlib wait: python:slim images ship neither pg_isready nor curl.
python - <<'PY'
import os, socket, time, urllib.parse, sys

url = os.environ.get("DATABASE_URL", "")
parsed = urllib.parse.urlparse(url.replace("postgres://", "postgresql://", 1))
host = parsed.hostname or "localhost"
port = parsed.port or 5432

for attempt in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"✅ Postgres reachable at {host}:{port}")
            sys.exit(0)
    except OSError:
        time.sleep(2)
print(f"❌ Database at {host}:{port} not reachable after 120s", file=sys.stderr)
sys.exit(1)
PY

echo "✅ Running Alembic migrations..."
alembic upgrade head

echo "✅ Migrations applied, starting API..."
exec uvicorn api_server:app --host 0.0.0.0 --port 8000
