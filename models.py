"""
SQLAlchemy models for Resume Classifier.
Defines ResumeResult with full metadata for enterprise persistence.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    """Naive UTC now (datetime.utcnow is deprecated on Python 3.12+)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    """User accounts (signup/login). Maps the users table created by the
    legacy migration; passwords are bcrypt hashes."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    is_admin = Column(Boolean, nullable=False, default=False)

    # Bumped on logout / forced sign-out. Session tokens embed the value they
    # were minted with, so incrementing this column revokes every outstanding
    # token for the user (stateless tokens are otherwise un-revocable).
    token_version = Column(Integer, nullable=False, default=0,
                           server_default="0")


class ResumeResult(Base):
    __tablename__ = "resume_results"

    # Unique job identifier
    job_id = Column(String, primary_key=True, index=True)

    # Owning user (nullable: anonymous jobs stay supported)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Original filename of the resume
    filename = Column(String, nullable=False)

    # Parsed resume text (for NLP downstream tasks)
    resume_text = Column(Text, nullable=True)

    # Job description used for matching
    job_description = Column(Text, nullable=True)

    # Resume vs JD keyword-overlap match score, as a percentage 0-100
    jd_match_score = Column(Float, nullable=True)

    # Skills extracted from the resume (comma-separated)
    skills_extracted = Column(Text, nullable=True)

    # sha256(resume bytes + jd) — duplicate prevention (unique index)
    resume_hash = Column(String, nullable=True, unique=True)

    # Predicted role/industry from the keyword-profile classifier
    predicted_role = Column(String, nullable=True)

    # JSON: name/email/phone/experience_years/education
    extracted_fields = Column(Text, nullable=True)

    # JSON: full match breakdown (semantic score, skill gaps, ...)
    match_details = Column(Text, nullable=True)

    # Current status of the job.
    #
    # PRODUCTION BUG (psycopg2 22P02 "invalid input value for enum jobstatus:
    # \"COMPLETED\""): migration 20260821 creates the Postgres type with the
    # LOWERCASE values -- sa.Enum('queued','processing','completed','failed').
    # A bare Enum(JobStatus) persists the Python member NAMES ('COMPLETED'),
    # which Postgres rejects, so every status write (and every query filtering
    # on status) failed in production while SQLite -- which does not enforce
    # enum labels -- happily accepted them in the test suite.
    #
    # values_callable pins the stored/bound representation to the member
    # VALUES, matching the type that already exists in the database.
    status = Column(
        Enum(JobStatus, name="jobstatus",
             values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        default=JobStatus.QUEUED,
    )

    # Timestamps.
    #
    # nullable=False mirrors the migration, which created both columns NOT
    # NULL with a server_default. The model previously said nullable=True --
    # harmless while the Python-side default always fires, but any code path
    # that set one of these to None explicitly would fail with an
    # IntegrityError that no SQLite test could reproduce (same blind spot as
    # the jobstatus enum). Keep model and schema in lockstep.
    created_at = Column(DateTime, nullable=False, default=_utcnow,
                        server_default=func.now())
    updated_at = Column(DateTime, nullable=False, default=_utcnow,
                        onupdate=_utcnow, server_default=func.now())
