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

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
