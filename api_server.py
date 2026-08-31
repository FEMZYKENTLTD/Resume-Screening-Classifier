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
import os
import time
import uuid
from collections import Counter

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func

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

app = FastAPI(title="Resume Classifier API (Sync)", version="5.2.0")

MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10 MB safety cap

ADMIN_USERNAMES = {
    u.strip().lower()
    for u in os.environ.get("ADMIN_USERNAMES", "admin").split(",")
    if u.strip()
}


# ------------------------------- infra -----------------------------------

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    if monitoring.registry is not None:
        path = request.url.path.rstrip("/") or "/"
        label = "/results/{job_id}" if path.startswith("/results/") else path
        monitoring.http_requests_total.labels(
            method=request.method, path=label, status=response.status_code
        ).inc()
        monitoring.http_request_seconds.labels(
            method=request.method, path=label
        ).observe(time.monotonic() - started)
    return response


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
    user_id = _current_user_id(x_user_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Valid login required (bad or missing token)")
    return user_id


def _require_admin(x_user_token: str | None) -> int:
    user_id = _require_user_id(x_user_token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
    if user is None or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


# ------------------------------- auth ------------------------------------

class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class SignupRequest(Credentials):
    email: str = Field(min_length=3, max_length=100)


def _is_admin_name(username: str) -> bool:
    return (username or "").strip().lower() in ADMIN_USERNAMES


def _user_payload(user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "is_admin": bool(user.is_admin),
        "token": auth.create_token(user.id),
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
        db.commit()
        db.refresh(user)
        return _user_payload(user)
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


# ------------------------------- analysis (SYNCHRONOUS DIRECT) --------------------------------

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
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    if len(payload) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume exceeds 10 MB limit.")

    user_id = _current_user_id(x_user_token) if x_user_token else None
    dedup_hash = make_dedup_hash(payload, jd)

    db = SessionLocal()
    try:
        # Check duplicate
        existing = db.query(ResumeResult).filter(
            ResumeResult.resume_hash == dedup_hash
        ).first()

        if existing is not None and existing.status == JobStatus.COMPLETED:
            if user_id and not existing.user_id:
                existing.user_id = user_id
                db.commit()
            return {
                "job_id": existing.job_id,
                "status": "completed",
                "jd_match_score": existing.jd_match_score,
                "skills_extracted": existing.skills_extracted,
                "predicted_role": existing.predicted_role,
                "extracted_fields": json.loads(existing.extracted_fields) if existing.extracted_fields else {},
                "match_details": json.loads(existing.match_details) if existing.match_details else {},
                "duplicate": True,
            }

        # Perform parsing & ML analysis synchronously right now
        text = parsing.parse_resume(filename, payload)
        keyword_score, _overlap = overlap_score(text, jd)
        role, role_method, role_confidence = classify_role_with_method(text)
        extracted = extract_fields(text)
        skills = ", ".join(sorted(extract_skills(text)))

        details = {
            "algorithm": "keyword-overlap",
            "keyword_score": keyword_score,
            "role_method": role_method,
            "role_confidence": role_confidence,
        }

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
        job.extracted_fields = json.dumps(extracted)
        job.match_details = json.dumps(details)
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
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(exc)}")
    finally:
        db.close()


@app.get("/results/{job_id}")
def get_results(job_id: str):
    db = SessionLocal()
    try:
        result = db.query(ResumeResult).filter(
            ResumeResult.job_id == job_id
        ).first()
    finally:
        db.close()

    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")

    def _json(raw):
        try:
            return json.loads(raw) if raw else None
        except (ValueError, TypeError):
            return None

    return {
        "job_id": result.job_id,
        "filename": result.filename,
        "jd_match_score": result.jd_match_score,
        "skills_extracted": result.skills_extracted,
        "predicted_role": result.predicted_role,
        "extracted_fields": _json(result.extracted_fields),
        "match_details": _json(result.match_details),
        "status": result.status.value,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
    }


@app.get("/history")
def history(x_user_token: str | None = Header(default=None)):
    user_id = _require_user_id(x_user_token)
    db = SessionLocal()
    try:
        rows = (
            db.query(ResumeResult)
            .filter(ResumeResult.user_id == user_id)
            .order_by(ResumeResult.created_at.desc())
            .limit(200)
            .all()
        )
    finally:
        db.close()

    return {
        "count": len(rows),
        "jobs": [
            {
                "job_id": r.job_id,
                "filename": r.filename,
                "jd_match_score": r.jd_match_score,
                "predicted_role": r.predicted_role,
                "skills_extracted": r.skills_extracted,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "extracted_fields": (
                    json.loads(r.extracted_fields) if r.extracted_fields else None
                ),
            }
            for r in rows
        ],
    }


@app.get("/analytics/summary")
def analytics_summary():
    db = SessionLocal()
    try:
        rows = db.query(ResumeResult).all()
        by_status = dict(
            db.query(ResumeResult.status, func.count())
            .group_by(ResumeResult.status).all()
        )
    finally:
        db.close()

    by_status = {k.value: v for k, v in by_status.items()}
    completed = [r for r in rows if r.status == JobStatus.COMPLETED]
    scores = [r.jd_match_score for r in completed if r.jd_match_score is not None]

    roles = Counter(r.predicted_role for r in completed if r.predicted_role)
    skills = Counter()
    for r in completed:
        if r.skills_extracted:
            skills.update(s.strip() for s in r.skills_extracted.split(",") if s.strip())

    buckets = Counter()
    for s in scores:
        bucket = min(int(s // 20) * 20, 80)
        buckets[f"{bucket}-{bucket + 20}"] += 1

    recent = sorted(rows, key=lambda r: r.created_at or 0, reverse=True)[:20]

    return {
        "total_jobs": len(rows),
        "by_status": by_status,
        "avg_match_score": round(sum(scores) / len(scores), 1) if scores else None,
        "score_histogram": dict(sorted(buckets.items())),
        "role_distribution": dict(roles.most_common()),
        "top_skills": [
            {"skill": k, "count": v} for k, v in skills.most_common(10)
        ],
        "recent_jobs": [
            {
                "job_id": r.job_id,
                "filename": r.filename,
                "jd_match_score": r.jd_match_score,
                "predicted_role": r.predicted_role,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ],
    }


# ------------------------------- admin -----------------------------------

def _day(d) -> str:
    return d.date().isoformat() if d else "unknown"


@app.get("/admin/overview")
def admin_overview(x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    db = SessionLocal()
    try:
        total_users = db.query(func.count(User.id)).scalar() or 0
        rows = db.query(ResumeResult).all()
    finally:
        db.close()

    now = dt.datetime.utcnow()
    week_ago = now - dt.timedelta(days=7)
    by_status = Counter(r.status.value for r in rows)
    scores = [r.jd_match_score for r in rows
              if r.status == JobStatus.COMPLETED and r.jd_match_score is not None]

    return {
        "total_users": total_users,
        "total_jobs": len(rows),
        "jobs_last_7d": sum(1 for r in rows if r.created_at and r.created_at >= week_ago),
        "by_status": dict(by_status),
        "avg_match_score": round(sum(scores) / len(scores), 1) if scores else None,
        "attributed_jobs": sum(1 for r in rows if r.user_id is not None),
    }


@app.get("/admin/users")
def admin_users(x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at).all()
        rows = db.query(ResumeResult).all()
    finally:
        db.close()

    per_user = {}
    for r in rows:
        if r.user_id is None:
            continue
        agg = per_user.setdefault(r.user_id, {
            "jobs": 0, "completed": 0, "failed": 0, "scores": [], "last": None,
        })
        agg["jobs"] += 1
        if r.status == JobStatus.COMPLETED:
            agg["completed"] += 1
            if r.jd_match_score is not None:
                agg["scores"].append(r.jd_match_score)
        elif r.status == JobStatus.FAILED:
            agg["failed"] += 1
        if r.created_at and (agg["last"] is None or r.created_at > agg["last"]):
            agg["last"] = r.created_at

    return {
        "count": len(users),
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "is_admin": bool(u.is_admin),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "jobs": per_user.get(u.id, {}).get("jobs", 0),
                "completed": per_user.get(u.id, {}).get("completed", 0),
                "failed": per_user.get(u.id, {}).get("failed", 0),
                "avg_score": (
                    round(sum(per_user[u.id]["scores"]) / len(per_user[u.id]["scores"]), 1)
                    if u.id in per_user and per_user[u.id]["scores"] else None
                ),
                "last_active": (
                    per_user[u.id]["last"].isoformat()
                    if u.id in per_user and per_user[u.id]["last"] else None
                ),
            }
            for u in users
        ],
    }


@app.get("/admin/users/{uid}/jobs")
def admin_user_jobs(uid: int, x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        rows = (db.query(ResumeResult)
                .filter(ResumeResult.user_id == uid)
                .order_by(ResumeResult.created_at.desc())
                .limit(200).all())
    finally:
        db.close()

    return {
        "user": {"id": user.id, "username": user.username, "email": user.email},
        "count": len(rows),
        "jobs": [
            {
                "job_id": r.job_id,
                "filename": r.filename,
                "jd_match_score": r.jd_match_score,
                "predicted_role": r.predicted_role,
                "skills_extracted": r.skills_extracted,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@app.get("/admin/trends")
def admin_trends(days: int = 30, x_user_token: str | None = Header(default=None)):
    _require_admin(x_user_token)
    days = max(1, min(days, 365))
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)

    db = SessionLocal()
    try:
        rows = db.query(ResumeResult).all()
        users = db.query(User).all()
    finally:
        db.close()

    jobs_per_day = Counter(
        _day(r.created_at) for r in rows
        if r.created_at and r.created_at >= cutoff
    )
    signups_per_day = Counter(
        _day(u.created_at) for u in users
        if u.created_at and u.created_at >= cutoff
    )

    completed = [r for r in rows if r.status == JobStatus.COMPLETED]
    roles = Counter(r.predicted_role for r in completed if r.predicted_role)
    skills = Counter()
    for r in completed:
        if r.skills_extracted:
            skills.update(s.strip() for s in r.skills_extracted.split(",") if s.strip())

    buckets = Counter()
    for r in completed:
        if r.jd_match_score is not None:
            b = min(int(r.jd_match_score // 20) * 20, 80)
            buckets[f"{b}-{b + 20}"] += 1

    return {
        "window_days": days,
        "jobs_per_day": dict(sorted(jobs_per_day.items())),
        "signups_per_day": dict(sorted(signups_per_day.items())),
        "profession_distribution": dict(roles.most_common()),
        "skill_distribution": [
            {"skill": k, "count": v} for k, v in skills.most_common(15)
        ],
        "score_histogram": dict(sorted(buckets.items())),
    }
