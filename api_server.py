"""
FastAPI entrypoint for the Resume Screening Classifier (Synchronous Direct Processing Mode).

Endpoints:
  GET  /health             -> liveness probe
  GET  /metrics            -> Prometheus scrape target
  POST /auth/signup        -> create an account (bcrypt), returns token
  POST /auth/login         -> returns token (case-insensitive username, synced is_admin)
  POST /single_analyze     -> SYNCHRONOUS parse, score, extract, and persist (blazing fast, no worker needed)
  GET  /results/{job_id}   -> get results directly
  GET  /history            -> the calling user's past analyses (X-User-Token)
  GET  /analytics/summary  -> recruiter analytics (aggregate)
  GET  /admin/*            -> admin dashboards (RBAC gated)
"""

import base64
import datetime as dt
import json
import logging
import os
import time
import traceback
import uuid

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import auth
import monitoring
import parsing
from database import SessionLocal
from extractors import extract_fields
from models import JobStatus, ResumeResult, User
from roles import classify_role_with_method
from scoring import overlap_score
from skills import extract_skills
from tasks import make_dedup_hash

logger = logging.getLogger("resumerank.api")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Resume Classifier API (Sync)", version="5.7.0")

MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10 MB safety cap
MAX_JD_CHARS = 20000                 # pasted-JD sanity cap
MAX_RESUME_CHARS = 200000            # parsed-text sanity cap (Postgres TEXT)

# Set DEBUG_ERRORS=1 to echo the exception type/message in 5xx responses.
DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS", "0").lower() in ("1", "true", "yes")

ADMIN_USERNAMES = {
    u.strip().lower()
    for u in os.environ.get("ADMIN_USERNAMES", "admin").split(",")
    if u.strip()
}

app.add_middleware(
    CORSMiddleware,
    # Lock down in production with CORS_ALLOW_ORIGINS=https://your-ui.example.com
    # (comma-separated). Default "*" keeps today's permissive demo behaviour.
    allow_origins=[
        o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """Record method/route/status/latency for every request (README: every
    request emits Prometheus metrics). Uses the route template as the path
    label so dynamic IDs don't explode label cardinality."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        monitoring.record_request(
            request.scope.get("route").path
            if request.scope.get("route") else "unmatched",
            method=request.method, status=500,
            seconds=time.perf_counter() - started,
        )
        raise
    route = request.scope.get("route")
    monitoring.record_request(
        getattr(route, "path", None) or "unmatched",
        method=request.method, status=response.status_code,
        seconds=time.perf_counter() - started,
    )
    return response


@app.on_event("startup")
def startup_event():
    monitoring.init_metrics()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    body, content_type = monitoring.metrics_response()
    return Response(content=body, media_type=content_type)


def _current_user_id(x_user_token: str | None) -> int | None:
    if not x_user_token:
        return None
    return auth.verify_token(x_user_token)


def _require_user_id(x_user_token: str | None) -> int:
    uid = _current_user_id(x_user_token)
    if uid is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


def _require_admin(x_user_token: str | None) -> int:
    user_id = _require_user_id(x_user_token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")
        return user_id
    finally:
        db.close()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class SignupRequest(Credentials):
    """Signup enforces the account policy; login deliberately stays lenient
    (any non-empty credentials) so wrong-password attempts surface as 401,
    not as validation errors. Lengths mirror the users table columns."""
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


def _is_admin_name(username: str) -> bool:
    return (username or "").strip().lower() in ADMIN_USERNAMES


def _user_payload(user: User) -> dict:
    token = auth.create_token(user.id)
    return {
        "token": token,
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": bool(user.is_admin),
    }


@app.post("/auth/signup", status_code=201)
def signup(payload: SignupRequest):
    db = SessionLocal()
    try:
        clash = db.query(User).filter(
            (func.lower(User.username) == payload.username.strip().lower()) | 
            (func.lower(User.email) == payload.email.strip().lower())
        ).first()
        if clash:
            raise HTTPException(
                status_code=409,
                detail="Username or email already registered",
            )
        user = User(
            username=payload.username.strip(),
            email=payload.email.strip(),
            password_hash=auth.hash_password(payload.password),
            is_admin=_is_admin_name(payload.username),
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Two signups for the same username/email raced past the SELECT
            # above and collided on the unique index. That is a client-visible
            # conflict, not a server fault.
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Username or email already registered",
            )
        db.refresh(user)
        return _user_payload(user)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("signup failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Storage backend unavailable, please retry in a moment.",
        )
    finally:
        db.close()


@app.post("/auth/login")
def login(payload: Credentials):
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            func.lower(User.username) == payload.username.strip().lower()
        ).first()
        if user is None or not auth.verify_password(
            payload.password, user.password_hash or ""
        ):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        should_be = _is_admin_name(user.username)
        if bool(user.is_admin) != should_be:
            user.is_admin = should_be
            db.commit()
        return _user_payload(user)
    finally:
        db.close()

@app.get("/auth/me")
def auth_me(x_user_token: str | None = Header(default=None)):
    """Validate a session token and return its user — lets the UI restore
    a login from a remembered cookie after a page refresh."""
    user_id = _require_user_id(x_user_token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="Unknown user")
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": bool(user.is_admin),
        }
    finally:
        db.close()

# ------------------------------- analysis (SYNCHRONOUS DIRECT) --------------------------------

def _safe_json(raw):
    """Stored JSON columns are read back defensively: one legacy/truncated row
    must never take down /single_analyze, /results or /history with a 500."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, (dict, list)) else {}


def _completed_payload(job, duplicate: bool) -> dict:
    return {
        "job_id": job.job_id,
        "status": "completed",
        "jd_match_score": job.jd_match_score,
        "skills_extracted": job.skills_extracted,
        "predicted_role": job.predicted_role,
        "extracted_fields": _safe_json(job.extracted_fields),
        "match_details": _safe_json(job.match_details),
        "duplicate": duplicate,
    }


@app.post("/single_analyze", status_code=200)
async def single_analyze(
    resume: UploadFile = File(...),
    jd: str = Form(...),
    x_user_token: str | None = Header(default=None),
):
    """
    Synchronously parses the resume, runs scoring, extraction, and role classification,
    saves directly to PostgreSQL/Supabase, and returns completed results instantly.
    """
    filename = resume.filename or "resume.pdf"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in parsing.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(parsing.SUPPORTED_EXTENSIONS)}",
        )

    payload = await resume.read()

    if len(payload) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume exceeds 10 MB limit.")
    if not payload:
        raise HTTPException(status_code=400, detail=f"'{filename}' is empty.")

    # The JD is user-typed and lands in a Postgres TEXT column: scrub NULs /
    # lone surrogates here too, and cap it so a pasted novel can't blow up the
    # row. Hash the SANITIZED jd so dedup stays consistent with what's stored.
    jd = parsing.sanitize_text(jd)[:MAX_JD_CHARS]
    if not jd:
        raise HTTPException(status_code=400, detail="Job description is empty.")

    user_id = _current_user_id(x_user_token) if x_user_token else None
    dedup_hash = make_dedup_hash(payload, jd)

    db = SessionLocal()
    try:
        existing = db.query(ResumeResult).filter(
            ResumeResult.resume_hash == dedup_hash
        ).first()

        if existing is not None and existing.status == JobStatus.COMPLETED:
            if user_id and not existing.user_id:
                existing.user_id = user_id
                db.commit()
            return _completed_payload(existing, duplicate=True)

        try:
            text = parsing.parse_resume(filename, payload)
        except HTTPException:
            raise
        except Exception as exc:
            # corrupt/encrypted/unreadable files are a client problem, not a
            # server fault — surface as 400, keep genuine crashes as 500
            raise HTTPException(
                status_code=400,
                detail=f"Could not parse '{filename}': {exc}",
            )
        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail=f"No readable text in '{filename}'. Scanned image PDFs "
                       "need OCR before upload.",
            )
        text = parsing.sanitize_text(text)[:MAX_RESUME_CHARS]

        keyword_score, _overlap = overlap_score(text, jd)

        # The ML extras (spaCy NER, sklearn role model) are OPTIONAL by design
        # (README: "graceful degradation"). A missing model file, an OOM-killed
        # spaCy load or a corrupt joblib artifact must degrade the result, not
        # 500 the request — this was the production failure mode.
        details = {
            "algorithm": "keyword-overlap",
            "keyword_score": keyword_score,
        }

        try:
            role, role_method, role_confidence = classify_role_with_method(text)
        except Exception as exc:
            logger.warning("role classification failed for %s: %s", filename, exc)
            role, role_method, role_confidence = "General / Uncategorized", "unavailable", None
            details["role_error"] = f"{type(exc).__name__}: {exc}"
        details["role_method"] = role_method
        details["role_confidence"] = role_confidence

        try:
            extracted = extract_fields(text)
        except Exception as exc:
            logger.warning("field extraction failed for %s: %s", filename, exc)
            extracted = {"extraction_method": "unavailable"}
            details["extraction_error"] = f"{type(exc).__name__}: {exc}"

        try:
            skills = ", ".join(sorted(extract_skills(text)))
        except Exception as exc:
            logger.warning("skill extraction failed for %s: %s", filename, exc)
            skills = ""
            details["skills_error"] = f"{type(exc).__name__}: {exc}"

        job_id = existing.job_id if existing else str(uuid.uuid4())
        
        if existing:
            job = existing
            job.status = JobStatus.PROCESSING
        else:
            job = ResumeResult(
                job_id=job_id,
                filename=filename,
                job_description=jd,
                resume_hash=dedup_hash,
                user_id=user_id,
                status=JobStatus.PROCESSING,
            )
            db.add(job)
        db.commit()

        job.resume_text = text
        job.jd_match_score = keyword_score
        job.skills_extracted = skills
        job.predicted_role = role
        job.extracted_fields = json.dumps(extracted, ensure_ascii=False, default=str)
        job.match_details = json.dumps(details, ensure_ascii=False, default=str)
        job.status = JobStatus.COMPLETED
        if user_id:
            job.user_id = user_id
        db.commit()

        return {
            "job_id": job_id,
            "status": "completed",
            "jd_match_score": keyword_score,
            "skills_extracted": skills,
            "predicted_role": role,
            "extracted_fields": extracted,
            "match_details": details,
            "duplicate": False,
        }
    except HTTPException:
        # client errors (400 bad file, etc.) must not be rewritten to 500
        db.rollback()
        raise
    except IntegrityError:
        # Two identical resumes submitted concurrently (batch screening races
        # on the resume_hash unique index). The other request won — serve its
        # completed row instead of failing the user's upload.
        db.rollback()
        winner = db.query(ResumeResult).filter(
            ResumeResult.resume_hash == dedup_hash
        ).first()
        if winner is not None:
            return _completed_payload(winner, duplicate=True)
        logger.exception("dedup race with no winning row for %s", filename)
        raise HTTPException(status_code=409, detail="Duplicate submission in flight; retry.")
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("DB failure analyzing %s: %s\n%s", filename, exc,
                     traceback.format_exc())
        raise HTTPException(
            status_code=503,
            detail="Storage backend unavailable, please retry in a moment."
                   + (f" [{type(exc).__name__}: {exc}]" if DEBUG_ERRORS else ""),
        )
    except Exception as exc:
        db.rollback()
        # Always log the full traceback server-side; the client gets a stable,
        # non-leaky message unless DEBUG_ERRORS is on.
        logger.error("Analysis failed for %s: %s\n%s", filename, exc,
                     traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail="Analysis failed due to an internal error."
                   + (f" [{type(exc).__name__}: {exc}]" if DEBUG_ERRORS else ""),
        )
    finally:
        db.close()


@app.get("/results/{job_id}")
def get_results(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(ResumeResult).filter(ResumeResult.job_id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "filename": job.filename,
            "jd_match_score": job.jd_match_score,
            "skills_extracted": job.skills_extracted,
            "predicted_role": job.predicted_role,
            "extracted_fields": _safe_json(job.extracted_fields),
            "match_details": _safe_json(job.match_details),
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
    finally:
        db.close()


@app.get("/history")
def history(x_user_token: str | None = Header(default=None)):
    user_id = _require_user_id(x_user_token)
    db = SessionLocal()
    try:
        jobs = (
            db.query(ResumeResult)
            .filter(ResumeResult.user_id == user_id)
            .order_by(ResumeResult.created_at.desc())
            .limit(200)
            .all()
        )
        return {
            "count": len(jobs),
            "jobs": [
                {
                    "job_id": j.job_id,
                    "filename": j.filename,
                    "status": j.status.value,
                    "jd_match_score": j.jd_match_score,
                    "skills_extracted": j.skills_extracted,
                    "predicted_role": j.predicted_role,
                    "extracted_fields": _safe_json(j.extracted_fields),
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in jobs
            ],
        }
    finally:
        db.close()


@app.get("/analytics/summary")
def analytics_summary():
    db = SessionLocal()
    try:
        rows = db.query(ResumeResult).all()
        total = len(rows)
        completed = [r for r in rows if r.status == JobStatus.COMPLETED]
        scores = [r.jd_match_score for r in completed if r.jd_match_score is not None]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        by_status = {}
        for r in rows:
            st = r.status.value if hasattr(r.status, "value") else str(r.status)
            by_status[st] = by_status.get(st, 0) + 1

        role_dist = {}
        skill_counts = {}
        for r in completed:
            if r.predicted_role:
                role_dist[r.predicted_role] = role_dist.get(r.predicted_role, 0) + 1
            if r.skills_extracted:
                for s in r.skills_extracted.split(","):
                    s_clean = s.strip()
                    if s_clean:
                        skill_counts[s_clean] = skill_counts.get(s_clean, 0) + 1

        top_skills = [
            {"skill": k, "count": v}
            for k, v in sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        recent = sorted(completed, key=lambda x: x.created_at or dt.datetime.min, reverse=True)[:10]
        recent_jobs = [
            {
                "job_id": r.job_id,
                "filename": r.filename,
                "status": r.status.value,
                "jd_match_score": r.jd_match_score,
                "predicted_role": r.predicted_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ]

        return {
            "total_jobs": total,
            "by_status": by_status,
            "avg_match_score": round(avg_score, 1),
            "score_histogram": _score_histogram(scores),
            "role_distribution": role_dist,
            "top_skills": top_skills,
            "recent_jobs": recent_jobs,
        }
    finally:
        db.close()


def _utcnow() -> dt.datetime:
    """Naive UTC now — datetime.utcnow() is deprecated on Python 3.12+;
    the DB stores naive UTC, so we drop tzinfo after conversion."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _day(d) -> str:
    return d.strftime("%Y-%m-%d") if d else "unknown"


def _score_histogram(scores) -> dict:
    """Ten 10-wide buckets (0-9 … 90-100) for the dashboards' score charts."""
    hist = {f"{lo}-{lo + 9}": 0 for lo in range(0, 100, 10)}
    for s in scores:
        lo = min(int(s // 10) * 10, 90)
        hist[f"{lo}-{lo + 9}"] += 1
    return hist


@app.get("/admin/overview")
def admin_overview(x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    db = SessionLocal()
    try:
        total_users = db.query(User).count()
        total_jobs = db.query(ResumeResult).count()
        completed = db.query(ResumeResult).filter(ResumeResult.status == JobStatus.COMPLETED).count()
        rows = db.query(ResumeResult).all()
        scores = [r.jd_match_score for r in rows if r.jd_match_score is not None]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        by_status: dict = {}
        for value, count in (
            db.query(ResumeResult.status, func.count(ResumeResult.job_id))
            .group_by(ResumeResult.status)
            .all()
        ):
            key = value.value if hasattr(value, "value") else str(value)
            by_status[key] = count

        week_ago = _utcnow() - dt.timedelta(days=7)
        jobs_last_7d = (
            db.query(ResumeResult)
            .filter(ResumeResult.created_at >= week_ago)
            .count()
        )

        return {
            "total_users": total_users,
            "total_jobs": total_jobs,
            "completed_jobs": completed,
            "avg_match_score": round(avg_score, 1),
            "by_status": by_status,
            "jobs_last_7d": jobs_last_7d,
        }
    finally:
        db.close()


@app.get("/admin/users")
def admin_users(x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()

        # Single scan of the results table; aggregate per user in Python.
        # (Simple and correct: scores are NULL until a job completes, so
        # averages must skip NULLs rather than trust SQL AVG over mixed rows.)
        rows = (
            db.query(
                ResumeResult.user_id,
                ResumeResult.status,
                ResumeResult.jd_match_score,
                ResumeResult.updated_at,
            )
            .all()
        )
        agg: dict = {}
        for uid, status, score, updated in rows:
            if uid is None:
                continue
            a = agg.setdefault(uid, {"jobs": 0, "completed": 0, "failed": 0,
                                     "scores": [], "last_active": None})
            a["jobs"] += 1
            st_key = status.value if hasattr(status, "value") else str(status)
            if st_key in ("completed", "failed"):
                a[st_key] += 1
            if score is not None:
                a["scores"].append(score)
            if updated is not None and (a["last_active"] is None or updated > a["last_active"]):
                a["last_active"] = updated

        out = []
        for u in users:
            a = agg.get(u.id, {"jobs": 0, "completed": 0, "failed": 0,
                               "scores": [], "last_active": None})
            avg_s = (sum(a["scores"]) / len(a["scores"])) if a["scores"] else None
            la = a["last_active"]
            out.append({
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "is_admin": bool(u.is_admin),
                "jobs": a["jobs"],
                "completed": a["completed"],
                "failed": a["failed"],
                "avg_score": round(avg_s, 1) if avg_s is not None else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_active": la.isoformat() if la else None,
            })
        return {"total": len(out), "users": out}
    finally:
        db.close()


@app.get("/admin/users/{uid}/jobs")
def admin_user_jobs(uid: int, x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        jobs = (db.query(ResumeResult)
                 .filter(ResumeResult.user_id == uid)
                 .order_by(ResumeResult.created_at.desc())
                 .limit(200)
                 .all())
        return {
            "user": {"id": user.id, "username": user.username, "email": user.email},
            "jobs": [
                {
                    "job_id": j.job_id,
                    "filename": j.filename,
                    "status": j.status.value,
                    "jd_match_score": j.jd_match_score,
                    "predicted_role": j.predicted_role,
                    # The admin drill-down table renders this column; omitting
                    # it made the whole Admin page crash with a pandas KeyError.
                    "skills_extracted": j.skills_extracted,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in jobs
            ],
        }
    finally:
        db.close()


@app.get("/admin/trends")
def admin_trends(days: int = 30, x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    days = max(1, min(days, 365))
    cutoff = _utcnow() - dt.timedelta(days=days)
    db = SessionLocal()
    try:
        jobs = db.query(ResumeResult).filter(ResumeResult.created_at >= cutoff).all()
        users = db.query(User).filter(User.created_at >= cutoff).all()

        jobs_per_day = {}
        prof_dist = {}
        skill_counts = {}
        for j in jobs:
            day_str = _day(j.created_at)
            jobs_per_day[day_str] = jobs_per_day.get(day_str, 0) + 1
            if j.predicted_role:
                prof_dist[j.predicted_role] = prof_dist.get(j.predicted_role, 0) + 1
            if j.skills_extracted:
                for s in j.skills_extracted.split(","):
                    s_clean = s.strip()
                    if s_clean:
                        skill_counts[s_clean] = skill_counts.get(s_clean, 0) + 1

        signups_per_day = {}
        for u in users:
            day_str = _day(u.created_at)
            signups_per_day[day_str] = signups_per_day.get(day_str, 0) + 1

        top_skills = [
            {"skill": k, "count": v}
            for k, v in sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        ]

        trend_scores = [
            j.jd_match_score for j in jobs if j.jd_match_score is not None
        ]

        return {
            "window_days": days,
            "jobs_per_day": jobs_per_day,
            "signups_per_day": signups_per_day,
            "profession_distribution": prof_dist,
            "skill_distribution": top_skills,
            "score_histogram": _score_histogram(trend_scores),
        }
    finally:
        db.close()