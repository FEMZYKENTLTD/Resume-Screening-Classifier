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

    # Current status of the job
    status = Column(Enum(JobStatus), default=JobStatus.QUEUED)

    # Timestamps
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)