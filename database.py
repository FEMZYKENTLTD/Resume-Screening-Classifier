"""
Database session management.

DATABASE_URL is read from the environment (set in docker-compose.yml,
Fly.io secrets, or a local .env). Falls back to the local docker-compose
Postgres for convenience.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@db:5432/resume_db"
)

# Some platforms still hand out legacy postgres:// URLs; SQLAlchemy 2.x
# only accepts postgresql://.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# How long a connection attempt may block before failing (seconds). Without
# this, a paused/unreachable database (e.g. a Supabase free tier that went to
# sleep) makes every request HANG on TCP connect until the platform proxy
# gives up and answers 502 with an EMPTY body — which the Streamlit UI then
# tried to parse as JSON and crashed with JSONDecodeError. Fail fast instead:
# the API returns a clean 503 and the UI shows "retry" instead of a traceback.
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))

_engine_kwargs: dict = {"pool_pre_ping": True}

if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        {
            "connect_args": {"connect_timeout": DB_CONNECT_TIMEOUT, "sslmode": "prefer"},
            # Supabase/managed Postgres kill idle connections; recycle well
            # before that so a stale pooled socket never reaches a request.
            "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "280")),
            "pool_timeout": DB_CONNECT_TIMEOUT,
        }
    )

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
