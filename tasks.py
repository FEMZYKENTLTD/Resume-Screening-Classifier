"""
Celery worker tasks for the Resume Screening Classifier.

Each task:
  1. parses the resume (PDF or DOCX)
  2. scores it with the shared keyword-overlap engine (percent 0-100)
  3. optionally blends in semantic embeddings (ENABLE_SEMANTIC=1)
  4. extracts skills + contact fields (spaCy NER when available)
  5. classifies the role (trained ML model when available, keywords otherwise)
  6. persists everything with a dedup hash (sha256 of resume+jd)
  7. emits Prometheus metrics

No DB connections happen at import time; Alembic owns the schema.
"""

import base64
import hashlib
import json
import os
import time

from celery import Celery

import matching_engine
import monitoring
import parsing
from database import SessionLocal
from extractors import extract_fields
from models import JobStatus, ResumeResult
from roles import classify_role_with_method
from scoring import overlap_score
from skills import extract_skills

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
ENABLE_SEMANTIC = os.environ.get("ENABLE_SEMANTIC", "").lower() in ("1", "true", "yes")

celery_app = Celery("tasks", broker=REDIS_URL)

# Optional worker-side /metrics endpoint (compose sets WORKER_METRICS_PORT)
if monitoring.maybe_start_worker_metrics_server():
    print("📈 worker metrics exposed on WORKER_METRICS_PORT")

# Headline score blend when semantic matching is enabled
SEMANTIC_WEIGHT = 0.65
KEYWORD_WEIGHT = 0.35


def make_dedup_hash(payload: bytes, jd: str) -> str:
    """Same resume content + same JD => same analysis => deduplicate."""
    return hashlib.sha256(payload + b"\x00" + jd.encode("utf-8")).hexdigest()


@celery_app.task(name="tasks.analyze_resume_task")
def analyze_resume_task(payload_b64: str, filename: str, jd: str, job_id: str,
                        user_id: int | None = None):
    """Parse a base64-encoded resume, score it against the JD, persist."""
    started = time.monotonic()
    payload = base64.b64decode(payload_b64)

    db = SessionLocal()
    job = ResumeResult(
        job_id=job_id,
        filename=filename,
        job_description=jd,
        resume_hash=make_dedup_hash(payload, jd),
        user_id=user_id,
        status=JobStatus.PROCESSING,
    )
    db.add(job)
    db.commit()

    try:
        text = parsing.sanitize_text(parsing.parse_resume(filename, payload))[:200000]

        keyword_score, _overlap = overlap_score(text, jd)
        score = keyword_score
        details = {"algorithm": "keyword-overlap", "keyword_score": keyword_score}

        if ENABLE_SEMANTIC:
            try:
                if matching_engine.semantic_available():
                    match = matching_engine.calculate_match(text, jd)
                    score = int(round(
                        SEMANTIC_WEIGHT * match["semantic_score"]
                        + KEYWORD_WEIGHT * keyword_score
                    ))
                    match["keyword_score"] = keyword_score
                    match["blended_weight"] = {
                        "semantic": SEMANTIC_WEIGHT, "keyword": KEYWORD_WEIGHT
                    }
                    details = match
                else:
                    details["semantic_note"] = (
                        "ENABLE_SEMANTIC=1 but ML stack not installed; used keywords"
                    )
            except Exception as exc:  # semantic must never break the pipeline
                details["semantic_error"] = f"{type(exc).__name__}: {exc}"

        try:
            role, role_method, role_confidence = classify_role_with_method(text)
        except Exception as exc:   # optional ML extras must degrade, not crash
            role, role_method, role_confidence = "General / Uncategorized", "unavailable", None
            details["role_error"] = f"{type(exc).__name__}: {exc}"

        try:
            extracted = extract_fields(text)
        except Exception as exc:
            extracted = {"extraction_method": "unavailable"}
            details["extraction_error"] = f"{type(exc).__name__}: {exc}"

        job.resume_text = text
        job.jd_match_score = score
        job.skills_extracted = ", ".join(sorted(extract_skills(text)))
        job.predicted_role = role
        job.extracted_fields = json.dumps(extracted, ensure_ascii=False, default=str)
        details["role_method"] = role_method
        details["role_confidence"] = role_confidence
        job.match_details = json.dumps(details, ensure_ascii=False, default=str)
        job.status = JobStatus.COMPLETED
        db.commit()

        monitoring.task_finished("completed", time.monotonic() - started, score)

        # Capture the result BEFORE the session closes: reading expired ORM
        # attributes on a closed session raises DetachedInstanceError.
        result_payload = {
            "job_id": job_id,
            "filename": filename,
            "jd_match_score": job.jd_match_score,
        }
        return result_payload
    except Exception:
        db.rollback()
        job.status = JobStatus.FAILED
        db.commit()
        monitoring.task_finished("failed", time.monotonic() - started)
        raise
    finally:
        db.close()
