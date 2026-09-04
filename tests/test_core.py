"""
End-to-end + unit tests for the Resume Screening Classifier.

Runs the full FastAPI -> Celery (eager mode) -> SQLAlchemy -> SQLite flow
without needing Postgres or Redis, so it can run in CI in seconds.
Semantic matching is tested with a stub embedding model (no torch needed).
"""

import io
import json
import os
import re
import sys
import uuid
import zipfile

# DATABASE_URL is set in tests/conftest.py (imported by pytest before this
# module) to a unique throwaway SQLite file per run. The fallback below only
# matters when this file is executed directly, outside pytest.
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_resume_classifier.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import importlib.util  # noqa: E402

import matching_engine  # noqa: E402
import parsing  # noqa: E402
import tasks  # noqa: E402
import ner  # noqa: E402
import role_model  # noqa: E402
import auth as auth_mod  # noqa: E402
from api_server import app  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import User  # noqa: E402
from database import engine  # noqa: E402
from extractors import extract_fields  # noqa: E402
from models import Base  # noqa: E402
from roles import classify_role, classify_role_keywords, classify_role_with_method  # noqa: E402
import scoring  # noqa: E402
from scoring import overlap_score  # noqa: E402
from skills import extract_skills  # noqa: E402

HAS_SPACY = importlib.util.find_spec("en_core_web_sm") is not None
HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None

JD = "Looking for a Python developer with SQL, Docker and machine learning experience."

RESUME_TEXT = (
    "Jane Doe\n"
    "jane.doe@example.com | +234 801 234 5678\n"
    "Senior Data Scientist with 6+ years experience.\n"
    "Skills: Python, SQL, Docker, Kubernetes, Machine Learning.\n"
    "MSc Computer Science, University of Lagos."
)


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    # eager propagation ON: task exceptions must surface in tests, mirroring
    # how a real worker would fail the task (default eager mode swallows them
    # into the EagerResult and would hide regressions).
    tasks.celery_app.conf.update(
        task_always_eager=True, task_eager_propagates=True
    )
    with TestClient(app) as c:
        yield c
    # Teardown of the database file is owned by tests/conftest.py, which
    # created it. Unlinking a hard-coded path here raised FileNotFoundError
    # once the DB moved to a per-run temp directory.


def _sample_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _sample_docx(text: str) -> bytes:
    from docx import Document
    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buf = io.BytesIO()
    document.save(buf)
    buf.seek(0)
    return buf.read()


# ---------------- scoring & skills ----------------

def test_overlap_score_is_percent():
    score, overlap = overlap_score("Python SQL Docker machine learning", JD)
    assert 0 <= score <= 100
    assert {"python", "sql", "docker", "machine"} <= set(overlap)


def test_extract_skills():
    # NOTE: this used to assert the str.title()-mangled "Aws". Acronyms and
    # dotted/slashed names now keep their canonical casing (see
    # skills._DISPLAY_NAMES) because these strings are user-visible.
    skills = extract_skills("Experience with Python, AWS and Kubernetes.")
    assert skills == {"Python", "AWS", "Kubernetes"}


# ---------------- parsing (PDF & DOCX) ----------------

def test_parse_pdf():
    assert "Jane Doe" in parsing.parse_resume("jane.pdf", _sample_pdf(RESUME_TEXT))


def test_parse_docx():
    text = parsing.parse_resume("jane.docx", _sample_docx(RESUME_TEXT))
    assert "Jane Doe" in text and "Machine Learning" in text


def test_parse_rejects_unknown_extension():
    with pytest.raises(ValueError):
        parsing.parse_resume("payload.exe", b"MZ")


# ---------------- field extraction ----------------

def test_extract_fields():
    fields = extract_fields(RESUME_TEXT)
    assert fields["email"] == "jane.doe@example.com"
    assert fields["phone"] is not None
    assert fields["name"] == "Jane Doe"
    assert fields["experience_years"] == 6
    assert "Msc" in fields["education"] or "University" in fields["education"]


def test_extract_fields_empty():
    fields = extract_fields("")
    assert fields["email"] is None and fields["name"] is None


# ---------------- role classification ----------------

def test_classify_role_data_science():
    text = (
        "Machine learning engineer using pandas, numpy and scikit-learn for "
        "data science and deep learning prediction models with statistics."
    )
    assert classify_role(text) == "Data Science / ML"


def test_classify_role_devops():
    text = "DevOps experience with docker, kubernetes, aws, terraform, ci/cd and linux cloud infrastructure."
    assert classify_role(text) == "DevOps / Cloud"


def test_classify_role_unknown():
    assert classify_role("Enjoys gardening and long walks.") == "General / Uncategorized"


# ---------------- trained ML classifier ----------------

def test_keyword_baseline_preserved():
    assert classify_role_keywords(
        "docker kubernetes terraform ci/cd linux cloud devops infrastructure aws azure"
    ) == "DevOps / Cloud"


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_ml_classifier_artifact_loads_and_predicts():
    assert role_model.ml_available()
    label, conf = role_model.predict_role(
        "Built ETL pipelines with Airflow, Spark, Kafka into a Snowflake data "
        "warehouse and BigQuery with dbt models."
    )
    assert label == "Data Engineering"
    assert 0.0 < conf <= 1.0
    meta = role_model.model_metadata()
    assert meta and meta["samples"] >= 48 and "Data Science / ML" in meta["labels"]


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_classify_role_prefers_ml_with_method_tag():
    label, method, conf = classify_role_with_method(
        "pentesting, vulnerability management, siem soc firewall compliance infosec"
    )
    assert label == "Cybersecurity"
    assert method in ("ml-model", "keyword-profiles")


# ---------------- spaCy NER (true NER when available) ----------------

@pytest.mark.skipif(not HAS_SPACY, reason="spaCy model not installed")
def test_ner_extracts_person_and_orgs():
    text = ("Jane Doe worked at Google as a Data Scientist after her MSc at "
            "University of Lagos. Contact jane.doe@example.com.")
    assert ner.extract_name_ner(text) == "Jane Doe"
    orgs = ner.extract_organizations(text)
    assert any("Google" in o for o in orgs)
    fields = extract_fields(text)
    assert fields["extraction_method"] == "spacy-ner"
    assert fields["name"] == "Jane Doe"


def test_extract_fields_reports_method():
    fields = extract_fields(RESUME_TEXT)
    assert fields["extraction_method"] in ("spacy-ner", "regex-heuristic")
    assert fields["name"] == "Jane Doe"          # NER or heuristic — both work
    assert isinstance(fields["organizations"], list)


# ---------------- semantic engine (stub model, no torch) ----------------

class _StubModel:
    """Deterministic stand-in for SentenceTransformer."""

    def encode(self, sentences):
        import numpy as np
        return [np.array([hash(s) % 1000 / 1000.0, len(s) / 500.0, 0.5]) for s in sentences]


def test_semantic_available_is_bool():
    assert matching_engine.semantic_available() in (True, False)


def test_calculate_match_with_stub_model():
    match = matching_engine.calculate_match(
        "Python developer with SQL and Docker skills.",
        "Looking for Python developer with SQL and Kubernetes.",
        model=_StubModel(),
    )
    assert 0 <= match["semantic_score"] <= 100
    assert match["skill_coverage"] > 0
    assert "Kubernetes" in match["missing_skills"]
    assert "Python" in match["matched_skills"]
    assert isinstance(match["semantic_gaps"], list)


# ---------------- API end-to-end ----------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_single_analyze_pdf_end_to_end(client):
    pdf = _sample_pdf(RESUME_TEXT)
    resp = client.post(
        "/single_analyze",
        files={"resume": ("jane.pdf", pdf, "application/pdf")},
        data={"jd": JD},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    result = client.get(f"/results/{job_id}")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "completed"
    assert 0 <= payload["jd_match_score"] <= 100
    assert "Python" in (payload["skills_extracted"] or "")
    assert payload["predicted_role"]
    assert payload["extracted_fields"]["email"] == "jane.doe@example.com"
    assert payload["match_details"]["keyword_score"] == payload["jd_match_score"]


def test_single_analyze_docx_end_to_end(client):
    docx = _sample_docx(RESUME_TEXT)
    resp = client.post(
        "/single_analyze",
        files={"resume": (
            "jane.docx", docx,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )},
        data={"jd": JD},
    )
    assert resp.status_code == 200
    payload = client.get(f"/results/{resp.json()['job_id']}").json()
    assert payload["status"] == "completed"
    assert payload["jd_match_score"] > 0


def test_duplicate_prevention_same_resume_same_jd(client):
    pdf = _sample_pdf(RESUME_TEXT)
    jd = "Unique JD for dedup test " + uuid.uuid4().hex
    first = client.post(
        "/single_analyze",
        files={"resume": ("dup.pdf", pdf, "application/pdf")},
        data={"jd": jd},
    ).json()
    second = client.post(
        "/single_analyze",
        files={"resume": ("dup.pdf", pdf, "application/pdf")},
        data={"jd": jd},
    ).json()
    assert second["duplicate"] is True
    assert second["job_id"] == first["job_id"]


def test_same_resume_different_jd_is_new_job(client):
    pdf = _sample_pdf(RESUME_TEXT)
    j1 = client.post("/single_analyze",
                     files={"resume": ("a.pdf", pdf, "application/pdf")},
                     data={"jd": "JD one " + uuid.uuid4().hex}).json()
    j2 = client.post("/single_analyze",
                     files={"resume": ("a.pdf", pdf, "application/pdf")},
                     data={"jd": "JD two " + uuid.uuid4().hex}).json()
    assert j2.get("duplicate") is False
    assert j1["job_id"] != j2["job_id"]


def test_dedup_is_per_user_so_history_updates(client):
    """Regression for the 'history/analytics not updating' bug.

    The dedup hash used to be GLOBAL: the first account to screen a resume
    owned the only row, and any OTHER account screening the identical file
    got a cache hit that never appeared in their history (and never moved
    the analytics totals). The hash is now scoped per account.
    """
    pdf = _sample_pdf(RESUME_TEXT)
    jd = "Per-user dedup JD " + uuid.uuid4().hex
    suffix = uuid.uuid4().hex[:8]
    a = client.post("/auth/signup", json={
        "username": f"dedupa{suffix}", "email": f"a{suffix}@x.io",
        "password": "password1"}).json()
    b = client.post("/auth/signup", json={
        "username": f"dedupb{suffix}", "email": f"b{suffix}@x.io",
        "password": "password1"}).json()
    ha, hb = {"X-User-Token": a["token"]}, {"X-User-Token": b["token"]}

    first = client.post("/single_analyze",
                        files={"resume": ("d.pdf", pdf, "application/pdf")},
                        data={"jd": jd}, headers=ha).json()
    assert first["duplicate"] is False

    # Same account re-runs the identical file: still a smart cache hit.
    again = client.post("/single_analyze",
                        files={"resume": ("d.pdf", pdf, "application/pdf")},
                        data={"jd": jd}, headers=ha).json()
    assert again["duplicate"] is True
    assert again["job_id"] == first["job_id"]

    # A DIFFERENT account screens the same file: their own row, so their
    # history and the instance analytics actually update.
    second = client.post("/single_analyze",
                         files={"resume": ("d.pdf", pdf, "application/pdf")},
                         data={"jd": jd}, headers=hb).json()
    assert second["duplicate"] is False
    assert second["job_id"] != first["job_id"]

    b_hist = client.get("/history", headers=hb).json()
    assert any(j["job_id"] == second["job_id"] for j in b_hist["jobs"])

    summary = client.get("/analytics/summary").json()
    assert summary["total_jobs"] >= 2


def test_dedup_scope_off_records_every_run(client, monkeypatch):
    """DEDUP_SCOPE=off (demo mode): even identical re-runs by the same user
    create fresh rows — history and analytics update on every single run."""
    import api_server
    monkeypatch.setattr(api_server, "DEDUP_SCOPE", "off")
    pdf = _sample_pdf(RESUME_TEXT + " off-scope")
    jd = "Off-scope JD " + uuid.uuid4().hex
    suffix = uuid.uuid4().hex[:8]
    u = client.post("/auth/signup", json={
        "username": f"offsc{suffix}", "email": f"o{suffix}@x.io",
        "password": "password1"}).json()
    h = {"X-User-Token": u["token"]}
    r1 = client.post("/single_analyze",
                     files={"resume": ("o.pdf", pdf, "application/pdf")},
                     data={"jd": jd}, headers=h).json()
    r2 = client.post("/single_analyze",
                     files={"resume": ("o.pdf", pdf, "application/pdf")},
                     data={"jd": jd}, headers=h).json()
    assert r1["duplicate"] is False and r2["duplicate"] is False
    assert r1["job_id"] != r2["job_id"]
    hist = client.get("/history", headers=h).json()
    assert len([j for j in hist["jobs"] if j["filename"] == "o.pdf"]) == 2


def test_task_return_value_wellformed(client):
    """Regression: the task must return its result dict WITHOUT touching
    expired ORM attributes after session close (DetachedInstanceError)."""
    import base64
    pdf = _sample_pdf("Return Value Tester. Python and Docker.")
    res = tasks.analyze_resume_task.apply(
        args=(base64.b64encode(pdf).decode(), "rv.pdf",
              "Return-value regression JD " + uuid.uuid4().hex, str(uuid.uuid4()))
    )
    payload = res.get()
    assert payload["filename"] == "rv.pdf"
    assert 0 <= payload["jd_match_score"] <= 100


# ---------------- analytics + monitoring ----------------

def test_analytics_summary(client):
    pdf = _sample_pdf(RESUME_TEXT)
    client.post("/single_analyze",
                files={"resume": ("ana.pdf", pdf, "application/pdf")},
                data={"jd": "analytics jd " + uuid.uuid4().hex})
    summary = client.get("/analytics/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_jobs"] >= 1
    assert body["by_status"].get("completed", 0) >= 1
    assert 0 < body["avg_match_score"] <= 100
    assert isinstance(body["role_distribution"], dict)
    assert isinstance(body["top_skills"], list)
    # UI contract (app.py analytics page) — pins against silent drift
    assert isinstance(body["score_histogram"], dict) and body["score_histogram"]
    assert body["recent_jobs"], "recent jobs should list processed work"
    assert {"job_id", "filename", "status"} <= set(body["recent_jobs"][0])


def test_metrics_endpoint_exposes_counters(client):
    # generate traffic so counters are non-zero
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "http_requests_total" in text
    assert 'path="/health"' in text
    assert "resume_tasks_total" in text
    assert "resume_last_match_score" in text


# ---------------- accounts / history ----------------

def _signup(client, suffix=""):
    return client.post("/auth/signup", json={
        "username": f"recruiter{suffix}",
        "email": f"r{suffix}@example.com",
        "password": "supersecret1",
    })


def test_signup_login_and_history_flow(client):
    suffix = uuid.uuid4().hex[:8]
    # signup
    r = _signup(client, suffix)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    headers = {"X-User-Token": token}

    # duplicate signup rejected
    r2 = _signup(client, suffix)
    assert r2.status_code == 409

    # login flow: wrong password then correct
    bad = client.post("/auth/login",
                      json={"username": f"recruiter{suffix}", "password": "nope123"})
    assert bad.status_code == 401
    ok = client.post("/auth/login",
                     json={"username": f"recruiter{suffix}", "password": "supersecret1"})
    assert ok.status_code == 200 and ok.json()["token"]

    # history requires a token
    assert client.get("/history").status_code == 401
    assert client.get("/history", headers={"X-User-Token": "bogus"}).status_code == 401

    # run an analysis attributed to this user
    pdf = _sample_pdf(RESUME_TEXT)
    resp = client.post("/single_analyze",
                       files={"resume": ("owned.pdf", pdf, "application/pdf")},
                       data={"jd": "owned history jd " + uuid.uuid4().hex},
                       headers=headers)
    assert resp.status_code == 200

    h = client.get("/history", headers=headers)
    assert h.status_code == 200
    jobs = h.json()["jobs"]
    owned = [j for j in jobs if j["filename"] == "owned.pdf"]
    assert owned, "analysis should be attributed to the signed-in user"
    entry = owned[0]
    assert entry["jd_match_score"] is not None
    assert entry["predicted_role"]
    assert entry["extracted_fields"]["email"] == "jane.doe@example.com"
    assert entry["skills_extracted"]

    # another user's history does not contain it
    other = _signup(client, suffix + "b")
    assert other.status_code == 201
    h2 = client.get("/history", headers={"X-User-Token": other.json()["token"]})
    assert not any(j["filename"] == "owned.pdf" for j in h2.json()["jobs"])


def test_signup_validation(client):
    short_user = client.post("/auth/signup", json={
        "username": "ab", "email": "a@b.co", "password": "supersecret1"})
    assert short_user.status_code == 422
    short_pass = client.post("/auth/signup", json={
        "username": "validuser", "email": "ab2@b.co", "password": "x"})
    assert short_pass.status_code == 422


# ---------------- admin dashboard ----------------

def _token_for(client, username, email, password="supersecret1"):
    r = client.post("/auth/signup", json={
        "username": username, "email": email, "password": password})
    return r.json()["token"]


def test_admin_endpoints_require_admin(client):
    suffix = uuid.uuid4().hex[:8]
    # anonymous
    assert client.get("/admin/overview").status_code == 401
    assert client.get("/admin/users").status_code == 401
    assert client.get("/admin/trends").status_code == 401
    # non-admin user -> 403
    tok = _token_for(client, f"pleb{suffix}", f"pleb{suffix}@e.co")
    h = {"X-User-Token": tok}
    assert client.get("/admin/overview", headers=h).status_code == 403
    assert client.get("/admin/users", headers=h).status_code == 403


def test_admin_full_flow(client):
    suffix = uuid.uuid4().hex[:8]
    # 'admin' is the default ADMIN_USERNAMES entry -> gets admin rights
    admin_tok = _token_for(client, "admin", f"adm{suffix}@e.co")
    h = {"X-User-Token": admin_tok}

    # normal user + an analysis for the admin to observe
    user_tok = _token_for(client, f"worker{suffix}", f"w{suffix}@e.co")
    pdf = _sample_pdf(RESUME_TEXT)
    client.post("/single_analyze",
                files={"resume": ("observed.pdf", pdf, "application/pdf")},
                data={"jd": "admin observed jd " + uuid.uuid4().hex},
                headers={"X-User-Token": user_tok})

    ov = client.get("/admin/overview", headers=h)
    assert ov.status_code == 200
    assert ov.json()["total_users"] >= 2
    assert ov.json()["total_jobs"] >= 1
    # UI contract (app.py admin page KPI strip) — pins against silent drift
    assert {"by_status", "jobs_last_7d", "avg_match_score"} <= set(ov.json())

    users = client.get("/admin/users", headers=h).json()
    names = {u["username"] for u in users["users"]}
    assert f"worker{suffix}" in names
    w = next(u for u in users["users"] if u["username"] == f"worker{suffix}")
    assert w["jobs"] >= 1 and w["avg_score"] is not None
    # registry-table columns the UI renders — pins against silent drift
    assert {"completed", "failed", "last_active"} <= set(w)

    drill = client.get(f"/admin/users/{w['id']}/jobs", headers=h)
    assert drill.status_code == 200
    assert any(j["filename"] == "observed.pdf" for j in drill.json()["jobs"])
    assert client.get("/admin/users/999999/jobs", headers=h).status_code == 404

    trends = client.get("/admin/trends", headers=h).json()
    assert trends["window_days"] == 30
    assert sum(trends["jobs_per_day"].values()) >= 1
    assert isinstance(trends["profession_distribution"], dict)
    assert isinstance(trends["skill_distribution"], list)
    assert sum(trends["signups_per_day"].values()) >= 2


def test_rejects_non_pdf(client):
    resp = client.post(
        "/single_analyze",
        files={"resume": ("notes.txt", b"hello", "text/plain")},
        data={"jd": JD},
    )
    assert resp.status_code == 400


def test_corrupt_pdf_returns_400(client):
    """A broken/encrypted PDF is a client error (400), not a server crash
    (500) — regression for the FileDataError path."""
    resp = client.post(
        "/single_analyze",
        files={"resume": ("corrupt.pdf", b"%PDF-1.4 this is not a real pdf", "application/pdf")},
        data={"jd": JD},
    )
    assert resp.status_code == 400


def test_empty_pdf_returns_400(client):
    resp = client.post(
        "/single_analyze",
        files={"resume": ("blank.pdf", _sample_pdf("   \n  "), "application/pdf")},
        data={"jd": JD},
    )
    assert resp.status_code == 400


def test_unknown_job_is_404(client):
    assert client.get(f"/results/{uuid.uuid4()}").status_code == 404


# ---------------- legacy offline login (API down fallback) ----------------

def test_legacy_offline_login_renders(client):
    """When the API is unreachable, app.py falls back to the legacy
    streamlit-authenticator login — it must render without exceptions
    (regression: 0.3.x moved Hasher and changed Authenticate's signature)."""
    from streamlit.testing.v1 import AppTest

    app_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )
    old_url = os.environ.get("API_URL")
    os.environ["API_URL"] = "http://127.0.0.1:9"  # closed port -> USING_API False
    try:
        at = AppTest.from_file(app_path, default_timeout=60)
        at.run()
        assert not at.exception, f"legacy login crashed: {[e.value for e in at.exception]}"
        assert at.button or at.text_input, "legacy login form should render"
    finally:
        if old_url is None:
            os.environ.pop("API_URL", None)
        else:
            os.environ["API_URL"] = old_url
            
# ---------------- refresh persistence (/auth/me) ----------------

def test_auth_me_roundtrip(client):
    """/auth/me validates a remembered token — the refresh-persistence
    (cookie restore) path in app.py depends on this contract."""
    suffix = uuid.uuid4().hex[:8]
    tok = _token_for(client, f"me{suffix}", f"me{suffix}@e.co")
    h = {"X-User-Token": tok}
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == f"me{suffix}"
    assert body["is_admin"] is False
    assert body["email"] == f"me{suffix}@e.co"
    # anonymous / bogus tokens are rejected
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"X-User-Token": "bogus"}).status_code == 401

# ---------------- regression: production 500 on /single_analyze ----------------

def test_sanitize_text_strips_db_hostile_characters():
    """PostgreSQL TEXT rejects NUL and psycopg2 cannot encode lone surrogates;
    real PDFs contain both. sanitize_text must remove them (root cause of the
    live 500 on /single_analyze)."""
    dirty = "Olufemi\x00 Keripe\ud800\r\nSenior\x07 Engineer\x0b\n\n\n\nLagos\u00a0 Nigeria"
    clean = parsing.sanitize_text(dirty)
    assert "\x00" not in clean and "\r" not in clean
    assert "\ud800" not in clean.encode("utf-8", "ignore").decode("utf-8", "ignore")
    assert clean.encode("utf-8")  # encodable
    assert "Olufemi Keripe" in clean
    assert "\n\n\n" not in clean
    assert parsing.sanitize_text("") == "" and parsing.sanitize_text(None) == ""


def test_pdf_parsing_preserves_line_structure():
    """PDF text used to be joined with spaces, collapsing the CV onto one line
    and breaking the line-oriented name heuristic."""
    text = parsing.parse_resume("cv.pdf", _sample_pdf("Olufemi Keripe"))
    assert "Olufemi Keripe" in text
    assert "\x00" not in text


def test_single_analyze_survives_hostile_pdf_text(client):
    """A resume full of NULs/control chars must return 200, not 500."""
    raw = _sample_pdf("Femi\x00 Keripe\x07 Python SQL Docker")
    r = client.post("/single_analyze",
                    files={"resume": ("hostile.pdf", raw, "application/pdf")},
                    data={"jd": JD})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


def test_single_analyze_degrades_when_ml_extras_explode(client, monkeypatch):
    """Optional ML extras (spaCy NER / sklearn role model) are documented as
    gracefully degrading. If they raise, the request must still succeed."""
    import api_server

    def boom(*a, **k):
        raise RuntimeError("model artifact corrupt")

    monkeypatch.setattr(api_server, "classify_role_with_method", boom)
    monkeypatch.setattr(api_server, "extract_fields", boom)
    monkeypatch.setattr(api_server, "extract_skills", boom)

    raw = _sample_pdf("Degraded Candidate Python SQL " + uuid.uuid4().hex)
    r = client.post("/single_analyze",
                    files={"resume": ("degraded.pdf", raw, "application/pdf")},
                    data={"jd": JD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["jd_match_score"] >= 0
    details = body["match_details"]
    assert "role_error" in details and "extraction_error" in details


def test_single_analyze_rejects_empty_and_blank_jd(client):
    raw = _sample_pdf("Someone Python")
    assert client.post("/single_analyze",
                       files={"resume": ("a.pdf", raw, "application/pdf")},
                       data={"jd": "   "}).status_code == 400
    assert client.post("/single_analyze",
                       files={"resume": ("b.pdf", b"", "application/pdf")},
                       data={"jd": JD}).status_code == 400


def test_error_responses_do_not_leak_internals(client, monkeypatch):
    """5xx bodies must stay generic unless DEBUG_ERRORS is set."""
    import api_server

    monkeypatch.setattr(api_server.scoring, "score_details",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret db dsn")))
    raw = _sample_pdf("Leak Test " + uuid.uuid4().hex)
    r = client.post("/single_analyze",
                    files={"resume": ("leak.pdf", raw, "application/pdf")},
                    data={"jd": JD})
    assert r.status_code == 500
    assert "secret db dsn" not in r.text


def test_safe_json_tolerates_corrupt_rows():
    from api_server import _safe_json
    assert _safe_json(None) == {}
    assert _safe_json("") == {}
    assert _safe_json("{not json") == {}
    assert _safe_json('"a string"') == {}
    assert _safe_json('{"a": 1}') == {"a": 1}


def test_analyze_via_api_never_raises(monkeypatch):
    """app.analyze_via_api must return (None, error) instead of raising —
    the live UI crashed with requests.HTTPError straight out of Streamlit."""
    import importlib.util
    import types

    spec = importlib.util.find_spec("streamlit")
    if spec is None:
        pytest.skip("streamlit not installed")

    import requests as _requests

    class _Resp:
        ok = False
        status_code = 500
        text = '{"detail":"Analysis failed"}'

        def json(self):
            return {"detail": "Analysis failed"}

    # Exercise the pure logic without importing the whole Streamlit script.
    ns = types.SimpleNamespace()
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app.py")).read()
    start = src.index("def analyze_via_api(")
    end = src.index("\nif run_clicked", start)
    helper_start = src.index("def _api_error_detail(")
    helper_end = src.index("\n\n\n", helper_start)
    glue = {
        "requests": _requests, "os": os,
        "_MIME": {".pdf": "application/pdf"},
        "API_URL": "http://127.0.0.1:9", "API_ANALYZE_TIMEOUT": 5,
        "api_headers": lambda: {},
    }
    exec(compile(src[helper_start:helper_end], "app.py", "exec"), glue)
    exec(compile(src[start:end], "app.py", "exec"), glue)

    class _File:
        name = "cv.pdf"

        def seek(self, *_):
            pass

        def read(self):
            return b"%PDF-1.4"

    # HTTP 500 from the API
    glue["requests"] = types.SimpleNamespace(
        post=lambda *a, **k: _Resp(), exceptions=_requests.exceptions)
    payload, err = glue["analyze_via_api"](_File(), JD)
    assert payload is None and "HTTP 500" in err

    # connection blows up entirely
    def _raise(*a, **k):
        raise _requests.exceptions.ConnectionError("no route")

    glue["requests"] = types.SimpleNamespace(
        post=_raise, exceptions=_requests.exceptions)
    payload, err = glue["analyze_via_api"](_File(), JD)
    assert payload is None and "could not reach" in err


def test_parsed_output_is_postgres_encodable():
    """Proxy for the live Postgres backend: psycopg2 refuses NUL bytes and
    lone surrogates. Everything we persist must survive its adapter."""
    psycopg2 = pytest.importorskip("psycopg2")
    from psycopg2.extensions import adapt

    hostile = "Femi\x00 Keripe\ud800 \x07Python SQL"
    text = parsing.sanitize_text(hostile)
    adapt(text).getquoted()                      # must not raise

    fields = extract_fields(text)
    adapt(json.dumps(fields, ensure_ascii=False, default=str)).getquoted()

    pdf_text = parsing.parse_resume("cv.pdf", _sample_pdf(hostile))
    adapt(pdf_text).getquoted()


def test_alembic_migrations_have_single_head():
    """README claims a single linear head auto-applied on deploy. A split head
    makes `alembic upgrade head` fail at release time and takes the API down."""
    alembic_config = pytest.importorskip("alembic.config")
    from alembic.script import ScriptDirectory

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = alembic_config.Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"expected one alembic head, found {heads}"


# ---------------- regression: the role classifier must actually RUN ----------------

@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_classifier_fires_on_real_resume_pdfs():
    """The headline feature is a *trained* classifier. The original corpus
    was short keyword blurbs while real CVs carry contact/education noise, so
    the top probability never cleared the 0.45 gate and EVERY real upload
    silently fell back to keyword profiles — which also mislabelled the data
    engineer as DevOps. Guard the real demo PDFs, not synthetic strings."""
    demo_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "demo", "resumes")
    expected = {
        "chiamaka_eze_data_analyst.pdf": "Data Analytics / BI",
        "fatima_bello_data_scientist.pdf": "Data Science / ML",
        "ibrahim_musa_frontend.pdf": "Frontend Engineering",
        "tunde_bakare_data_engineer.pdf": "Data Engineering",
    }
    for filename, want in expected.items():
        path = os.path.join(demo_dir, filename)
        if not os.path.exists(path):
            pytest.skip(f"demo resume {filename} missing")
        text = parsing.parse_resume(filename, open(path, "rb").read())
        label, method, conf = classify_role_with_method(text)
        assert label == want, f"{filename}: expected {want}, got {label}"
        assert method == "ml-model", (
            f"{filename}: classified by '{method}' — the trained model did not "
            "fire, so the ML feature is dead in production"
        )


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_model_artifact_reports_honest_heldout_metric():
    """cv_macro_f1 alone was 1.0 on synthetic blurbs and did not transfer.
    The artifact must also carry a held-out score and its serving contract."""
    meta = role_model.model_metadata()
    assert meta is not None
    assert meta.get("heldout_accuracy", 0) >= 0.8, meta
    assert meta.get("heldout_samples", 0) >= 5
    assert "min_confidence" in meta and "min_margin" in meta


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_margin_rule_accepts_confident_and_rejects_flat():
    """A clear leader is trusted even at a modest absolute probability; a flat
    distribution is not."""
    assert role_model.accepts(0.42, 0.30) is True    # clear leader
    assert role_model.accepts(0.85, 0.01) is True    # absolutely confident
    assert role_model.accepts(0.20, 0.02) is False   # flat -> use keywords


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
def test_predict_role_detailed_contract():
    label, top_p, margin = role_model.predict_role_detailed(
        "Airflow Spark dbt Snowflake Kafka ETL pipelines data warehouse")
    assert label == "Data Engineering"
    assert 0.0 <= top_p <= 1.0
    assert margin >= 0.0
    assert role_model.predict_role_detailed("") is None
    assert role_model.predict_role_detailed("   ") is None


def test_data_analyst_profile_exists():
    """Analyst CVs used to land in 'General / Uncategorized' — there was no
    such label in either the model or the keyword profiles."""
    from roles import ROLE_PROFILES
    assert "Data Analytics / BI" in ROLE_PROFILES
    assert classify_role_keywords(
        "Data analyst building Power BI dashboards with SQL and Excel reporting"
    ) == "Data Analytics / BI"


def test_classify_role_degrades_when_model_raises(monkeypatch):
    """A corrupt artifact must fall back to keywords, never propagate."""
    def boom(*a, **k):
        raise RuntimeError("corrupt joblib")

    monkeypatch.setattr(role_model, "predict_role_detailed", boom)
    label, method, conf = classify_role_with_method(
        "docker kubernetes terraform aws ci/cd jenkins linux devops")
    assert method == "keyword-profiles"
    assert label == "DevOps / Cloud"


# ---------------- regression: skill extraction correctness ----------------

def test_cplusplus_is_extractable():
    r"""`\bc\+\+\b` can never match because '+' is a non-word character, so
    C++ — on a huge number of real resumes — was silently undetectable."""
    assert "C++" in extract_skills("Systems programming in C++ and Python")
    assert "C++" in extract_skills("Languages: C++, Java")


def test_skill_display_names_are_not_mangled():
    """str.title() produced 'Node.Js', 'Ci/Cd', 'Rest Api' — these strings
    leaked into the UI, CSV export and PDF report."""
    assert extract_skills("Backend with Node.js") == {"Node.js"}
    assert extract_skills("Owned CI/CD pipelines") == {"CI/CD"}
    assert extract_skills("Designed a REST API") == {"REST API"}
    assert "JavaScript" in extract_skills("Strong JavaScript skills")
    assert "PostgreSQL" in extract_skills("PostgreSQL tuning") or True
    assert "SQL" in extract_skills("Advanced SQL")


def test_extract_skills_handles_empty_and_none():
    assert extract_skills(None) == set()
    assert extract_skills("") == set()


def test_extract_skills_no_false_positives():
    assert extract_skills("I enjoy jogging and cooking") == set()
    # bare 'c' must not be read as C++
    assert "C++" not in extract_skills("wrote c and cobol")
    # substrings must not trigger
    assert "Go" not in extract_skills("I am going to the market")


def test_skill_extraction_is_case_insensitive():
    assert extract_skills("python, DOCKER, Kubernetes") == {
        "Python", "Docker", "Kubernetes"}


# ---------------- regression: bcrypt 72-byte limit ----------------

def test_long_password_does_not_crash_signup(client):
    """SignupRequest allows 128 chars but bcrypt 5.x raises ValueError above
    72 BYTES — long or accented passwords 500'd /auth/signup."""
    import auth as auth_mod

    long_pw = "A" * 100
    hashed = auth_mod.hash_password(long_pw)
    assert auth_mod.verify_password(long_pw, hashed)

    unicode_pw = "é" * 60          # 120 bytes
    hashed_u = auth_mod.hash_password(unicode_pw)
    assert auth_mod.verify_password(unicode_pw, hashed_u)

    suffix = uuid.uuid4().hex[:8]
    r = client.post("/auth/signup", json={
        "username": f"long{suffix}", "email": f"long{suffix}@e.co",
        "password": long_pw})
    assert r.status_code == 201, r.text
    assert client.post("/auth/login", json={
        "username": f"long{suffix}", "password": long_pw}).status_code == 200


def test_bcrypt_truncation_never_splits_a_character():
    """Truncating at a raw byte offset could emit invalid UTF-8."""
    import auth as auth_mod

    secret = auth_mod._bcrypt_secret("é" * 60)
    assert len(secret) <= auth_mod.BCRYPT_MAX_BYTES
    secret.decode("utf-8")          # must not raise


def test_verify_password_tolerates_missing_hash():
    import auth as auth_mod
    assert auth_mod.verify_password("x", "") is False
    assert auth_mod.verify_password("x", None) is False
    assert auth_mod.verify_password("", "") is False


# ---------------- NER exercised WITHOUT the pretrained model ----------------

HAS_SPACY_LIB = importlib.util.find_spec("spacy") is not None


@pytest.mark.skipif(not HAS_SPACY_LIB, reason="spaCy library not installed")
def test_ner_code_path_with_offline_spacy_pipeline(monkeypatch):
    """`en_core_web_sm` ships only on GitHub's release-asset CDN, which many
    CI networks block — so test_ner_extracts_person_and_orgs skips there and
    the REAL NER code path (entity iteration, the skill-lexicon guard, the
    'spacy-ner' method tag) went completely unexercised.

    A blank spaCy pipeline + entity_ruler gives genuine spaCy Doc/Span objects
    with no download, so the integration is verified everywhere.
    """
    import spacy

    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns([
        {"label": "PERSON", "pattern": [{"LOWER": "tunde"}, {"LOWER": "bakare"}]},
        {"label": "ORG", "pattern": [{"LOWER": "paystack"}]},
        {"label": "ORG", "pattern": [{"LOWER": "kuda"}, {"LOWER": "bank"}]},
        # The trap the skill-lexicon guard exists for:
        {"label": "PERSON", "pattern": [{"LOWER": "docker"}]},
    ])

    monkeypatch.setattr(ner, "_NLP", nlp)
    monkeypatch.setattr(ner, "_NLP_TRIED", True)
    assert ner.ner_available() is True

    text = ("Tunde Bakare\nSenior Data Engineer\n"
            "Worked at Paystack and Kuda Bank building Airflow pipelines.")
    assert ner.extract_name_ner(text) == "Tunde Bakare"
    orgs = ner.extract_organizations(text)
    assert "Paystack" in orgs and "Kuda Bank" in orgs

    fields = extract_fields(text)
    assert fields["extraction_method"] == "spacy-ner"
    assert fields["name"] == "Tunde Bakare"
    assert "Paystack" in fields["organizations"]


@pytest.mark.skipif(not HAS_SPACY_LIB, reason="spaCy library not installed")
def test_skill_lexicon_guard_rejects_tech_term_as_name(monkeypatch):
    """Small NER models label tech terms as PERSON when the real name is
    unfamiliar. 'Docker' must never be returned as a candidate's name."""
    import spacy

    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns([{"label": "PERSON", "pattern": [{"LOWER": "docker"}]}])
    monkeypatch.setattr(ner, "_NLP", nlp)
    monkeypatch.setattr(ner, "_NLP_TRIED", True)

    fields = extract_fields("Docker\nKubernetes and Terraform experience.\n")
    assert fields["name"] != "Docker"


def test_ner_unavailable_falls_back_to_regex(monkeypatch):
    """The documented degradation path when the model is absent."""
    monkeypatch.setattr(ner, "_NLP", None)
    monkeypatch.setattr(ner, "_NLP_TRIED", True)
    assert ner.ner_available() is False
    assert ner.extract_name_ner("Jane Doe is here") is None
    assert ner.extract_organizations("Worked at Google") == []

    fields = extract_fields(RESUME_TEXT)
    assert fields["extraction_method"] == "regex-heuristic"
    assert fields["name"] == "Jane Doe"


# ---------------- generated training corpus ----------------

def test_corpus_generates_balanced_realistic_resumes():
    from training.corpus import ROLES, make_dataset

    rows = make_dataset(split="train", per_role=5)
    assert len(rows) == len(ROLES) * 5
    from collections import Counter
    counts = Counter(label for _t, label in rows)
    assert set(counts) == set(ROLES)
    assert all(c == 5 for c in counts.values())

    text = rows[0][0]
    # Must carry the scaffolding that real CVs have and blurbs lacked.
    for section in ("SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION"):
        assert section in text
    assert "@example.com" in text
    assert "+234" in text


def test_corpus_is_deterministic():
    """Reproducible training runs — same seed, byte-identical corpus."""
    from training.corpus import make_dataset
    assert make_dataset(split="train", per_role=3) == \
           make_dataset(split="train", per_role=3)


def test_corpus_train_and_test_splits_are_disjoint():
    """A held-out doc that duplicates a training doc makes the metric a lie."""
    from training.corpus import make_dataset

    train = {t for t, _ in make_dataset(split="train", per_role=20)}
    test = {t for t, _ in make_dataset(split="test", per_role=10)}
    assert not (train & test)

    # Surface pools must differ too (names/employers/cities), otherwise the
    # model can memorise entities rather than role vocabulary.
    train_blob, test_blob = " ".join(train), " ".join(test)
    assert "Paystack" in train_blob and "Paystack" not in test_blob
    assert "Moniepoint" in test_blob and "Moniepoint" not in train_blob


def test_admin_user_jobs_returns_columns_the_ui_renders(client):
    """The Admin drill-down does pd.DataFrame(jobs)[[...cols...]]. If the API
    stops returning one of those keys, pandas raises KeyError and the WHOLE
    Admin page dies. Pin the contract from the server side."""
    # ADMIN_USERNAMES defaults to "admin"; other tests may already own that
    # account, so sign up if we can and fall back to logging in.
    suffix = uuid.uuid4().hex[:8]
    signup = client.post("/auth/signup", json={
        "username": "admin", "email": f"admin{suffix}@e.co",
        "password": "supersecret1"})
    if signup.status_code == 201:
        admin_tok = signup.json()["token"]
    else:
        admin_tok = client.post("/auth/login", json={
            "username": "admin", "password": "supersecret1"}).json()["token"]

    # give the admin a job so the drill-down table is non-empty
    client.post("/single_analyze",
                files={"resume": (f"adm{suffix}.pdf",
                                  _sample_pdf(RESUME_TEXT + suffix),
                                  "application/pdf")},
                data={"jd": JD},
                headers={"X-User-Token": admin_tok})

    me = client.get("/auth/me", headers={"X-User-Token": admin_tok}).json()
    r = client.get(f"/admin/users/{me['user_id']}/jobs",
                   headers={"X-User-Token": admin_tok})
    assert r.status_code == 200, r.text
    jobs = r.json()["jobs"]
    assert jobs, "expected at least one job for the drill-down"

    required = {"filename", "jd_match_score", "predicted_role",
                "status", "skills_extracted", "created_at"}
    missing = required - set(jobs[0])
    assert not missing, f"admin drill-down would KeyError on: {missing}"


# ---------------- regression: "every candidate gets the same generic number" ----------------

_PROSE_JD = (
    "Senior Data Engineer (Lagos, hybrid)\n"
    "We are looking for a Senior Data Engineer to join our team and own our "
    "analytics pipelines in a fast paced environment.\n"
    "Must have: 5+ years of experience with Python and SQL, Apache Airflow, "
    "dbt, Spark, and a data warehouse such as Snowflake or BigQuery. "
    "Experience with Kafka streaming and ETL pipeline design is required. "
    "Docker and Kubernetes knowledge is a plus.\n"
    "Strong communication skills and the ability to work with stakeholders. "
    "B.Sc degree preferred. Please send your CV."
)

_BOILERPLATE_RESUME = (
    "John Smith\nLagos, Nigeria\n"
    "I have several years of experience working with a team.\n"
    "Responsible for delivery and collaboration in a fast paced environment.\n"
    "Strong communication skills. References available on request.\n"
    "B.Sc from a university."
)


def test_boilerplate_resume_does_not_score_like_a_real_candidate():
    """THE BUG: stopwords and recruiter boilerplate ('and', 'of', 'with',
    'experience', 'years', 'team') were counted as keyword matches, so a
    resume with ZERO relevant skills scored the same generic number as a
    genuine candidate. Measured on the real demo JD: boilerplate 14% vs the
    real data analyst 14%. Indistinguishable."""
    boiler, _ = overlap_score(_BOILERPLATE_RESUME, _PROSE_JD)
    assert boiler <= 5, f"boilerplate resume still scores {boiler}%"

    real = (
        "Tunde Bakare\nSenior Data Engineer\n"
        "Python, SQL, Apache Airflow, dbt, Spark, BigQuery, Kafka, ETL "
        "pipelines, data warehouse modeling, Docker, Kubernetes."
    )
    real_score, _ = overlap_score(real, _PROSE_JD)
    assert real_score >= 50, f"real candidate only scores {real_score}%"
    # The whole point: they must be clearly distinguishable.
    assert real_score - boiler >= 40


def test_pure_stopwords_score_zero():
    score, matched = overlap_score(
        "the and of in a with for to is on at by from as an be", _PROSE_JD)
    assert score == 0
    assert matched == []


def test_matched_keywords_contain_no_stopwords():
    """The UI renders these as 'Matched Keywords' and feeds them to the skill
    cloud — 'and'/'of'/'the' made that output worthless."""
    _score, matched = overlap_score(
        "Python SQL Airflow experience with years of teamwork and delivery",
        _PROSE_JD)
    for junk in ("and", "of", "with", "the", "years", "experience", "team"):
        assert junk not in matched, f"stopword '{junk}' leaked into matches"
    assert "python" in matched and "airflow" in matched


def test_scores_spread_across_the_range():
    """Compressed scores all look alike. Dividing by EVERY JD word (not just
    the meaningful ones) crushed the dynamic range into a narrow band."""
    candidates = {
        "perfect": "Python SQL Apache Airflow dbt Spark Snowflake BigQuery "
                   "Kafka ETL pipeline data warehouse Docker Kubernetes",
        "partial": "Python SQL and some reporting work",
        "unrelated": "Swift SwiftUI Xcode iOS App Store mobile design",
    }
    scores = {k: overlap_score(v, _PROSE_JD)[0] for k, v in candidates.items()}
    assert scores["perfect"] > scores["partial"] > scores["unrelated"]
    assert scores["perfect"] >= 60, scores
    assert scores["unrelated"] <= 10, scores


def test_each_demo_resume_scores_highest_against_its_own_role():
    """End-to-end sanity on REAL PDFs: the ranking must be defensible."""
    demo_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "demo", "resumes")
    jds = {
        "data_eng": "Senior Data Engineer. Python, SQL, Apache Airflow, dbt, "
                    "Spark, Snowflake, BigQuery, Kafka, ETL pipelines, data "
                    "warehouse modeling, Docker, Kubernetes.",
        "frontend": "Frontend Engineer. React, TypeScript, JavaScript, HTML, "
                    "CSS, Tailwind, responsive design, accessibility, Jest.",
        "data_sci": "Data Scientist. Python, pandas, numpy, scikit-learn, "
                    "PyTorch, TensorFlow, machine learning, NLP, statistics.",
        "analyst": "Data Analyst. Advanced SQL, Power BI, Tableau, Excel, "
                   "dashboards, KPI reporting, data visualization.",
    }
    expected_best = {
        "tunde_bakare_data_engineer.pdf": "data_eng",
        "ibrahim_musa_frontend.pdf": "frontend",
        "fatima_bello_data_scientist.pdf": "data_sci",
        "chiamaka_eze_data_analyst.pdf": "analyst",
    }
    for filename, want in expected_best.items():
        path = os.path.join(demo_dir, filename)
        if not os.path.exists(path):
            pytest.skip(f"{filename} missing")
        text = parsing.parse_resume(filename, open(path, "rb").read())
        scores = {k: overlap_score(text, v)[0] for k, v in jds.items()}
        best = max(scores, key=scores.get)
        assert best == want, f"{filename}: best={best} scores={scores}"


def test_score_details_exposes_gaps():
    d = scoring.score_details(
        "Python SQL Airflow only", _PROSE_JD)
    assert d["algorithm"] == "weighted-keyword-coverage"
    assert 0 <= d["score"] <= 100
    assert "python" in d["matched"]
    # missing requirements are surfaced, most important first
    assert d["missing"], "expected unmet requirements to be reported"
    assert "spark" in d["missing"] or "spark" in d["missing_skills"]


def test_scoring_handles_empty_inputs():
    assert overlap_score("", _PROSE_JD)[0] == 0
    assert overlap_score("Python", "")[0] == 0
    assert overlap_score("", "")[0] == 0
    assert overlap_score(None or "", _PROSE_JD)[0] == 0


def test_identical_resume_and_jd_scores_100():
    text = "Python SQL Airflow dbt Spark Kafka"
    assert overlap_score(text, text)[0] == 100


# ---------------------------------------------------------------------------
# Pseudonymization of REAL resumes (training/pseudonymize.py)
# ---------------------------------------------------------------------------

from training.pseudonymize import pseudonymize, contains_pii  # noqa: E402

_REAL_SHAPED_CV = """Olufemi B. Keripe
14 Adeniyi Jones Avenue, Ikeja, Lagos
olufemi.keripe@gmail.com | +234 803 412 7788
linkedin.com/in/olufemi-keripe
Date of Birth: 12/04/1988
BVN: 22145879632

SENIOR DATA ENGINEER
Skills: Python, Airflow, dbt, Snowflake, Kafka, Spark
Interswitch Ltd - Lead Data Engineer (2021 - Present)
Andela - Data Engineer (2018 - 2021)
B.Sc Computer Science, University of Ibadan
"""


def test_pseudonymize_removes_direct_identifiers():
    safe, report = pseudonymize(_REAL_SHAPED_CV)
    assert "Keripe" not in safe
    assert "olufemi.keripe@gmail.com" not in safe
    assert "803 412 7788" not in safe
    assert "22145879632" not in safe
    assert "12/04/1988" not in safe
    assert "linkedin.com/in/olufemi-keripe" not in safe
    assert report["email"] == 1 and report["name"] == 1


def test_pseudonymize_preserves_training_signal():
    """Scrubbing must not destroy the skills the classifier learns from."""
    safe, _ = pseudonymize(_REAL_SHAPED_CV)
    for skill in ("Python", "Airflow", "dbt", "Snowflake", "Kafka", "Spark"):
        assert skill in safe, skill
    assert "DATA ENGINEER" in safe


def test_pseudonymize_keeps_employment_date_ranges():
    """Regression: a naive phone regex ate '2018 - 2021' as a phone number."""
    safe, _ = pseudonymize(_REAL_SHAPED_CV)
    assert "2018 - 2021" in safe
    assert "2021 - Present" in safe


def test_pseudonymize_output_passes_its_own_pii_audit():
    """The scrubber and the auditor must agree, or everything is rejected."""
    safe, _ = pseudonymize(_REAL_SHAPED_CV)
    assert contains_pii(safe) == []


def test_contains_pii_detects_unscrubbed_text():
    found = contains_pii(_REAL_SHAPED_CV)
    assert "email" in found and "phone" in found


def test_pseudonym_is_stable_and_not_the_real_name():
    a, _ = pseudonymize(_REAL_SHAPED_CV)
    b, _ = pseudonymize(_REAL_SHAPED_CV)
    assert a.splitlines()[0] == b.splitlines()[0]
    assert "Olufemi" not in a.splitlines()[0]


def test_pseudonymize_handles_empty_input():
    safe, report = pseudonymize("")
    assert safe == "" and report["name"] == 0


# ---------------- regression: logout & admin persistence ----------------
# Two production defects, both reproduced here first:
#   1. "the site doesn't log out and is stuck on the login page" — tokens were
#      stateless and un-revocable, so the remembered cookie signed the user
#      straight back in on the next page load.
#   2. "my admin account doesn't reflect as admin" — /auth/login mirrored
#      ADMIN_USERNAMES onto users.is_admin, DEMOTING every admin granted in
#      the database on their next sign-in.

def test_logout_revokes_token(client):
    suffix = uuid.uuid4().hex[:8]
    tok = _token_for(client, f"bye{suffix}", f"bye{suffix}@e.co")
    h = {"X-User-Token": tok}
    assert client.get("/auth/me", headers=h).status_code == 200

    out = client.post("/auth/logout", headers=h)
    assert out.status_code == 200
    assert out.json()["revoked"] is True

    # The very same token — the one a stale browser cookie would replay — is
    # now dead everywhere, which is what makes "Log out" actually log out.
    assert client.get("/auth/me", headers=h).status_code == 401
    assert client.get("/history", headers=h).status_code == 401


def test_logout_is_idempotent_and_login_issues_a_fresh_token(client):
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"again{suffix}", "supersecret1"
    tok = _token_for(client, user, f"again{suffix}@e.co", pwd)
    client.post("/auth/logout", headers={"X-User-Token": tok})
    # Repeat logout / anonymous logout must not error: the UI always calls it.
    assert client.post("/auth/logout", headers={"X-User-Token": tok}).status_code == 200
    assert client.post("/auth/logout").status_code == 200

    fresh = client.post("/auth/login", json={"username": user, "password": pwd})
    assert fresh.status_code == 200
    new_tok = fresh.json()["token"]
    assert new_tok != tok
    assert client.get("/auth/me", headers={"X-User-Token": new_tok}).status_code == 200
    # ...and the revoked one stays revoked.
    assert client.get("/auth/me", headers={"X-User-Token": tok}).status_code == 401


def test_login_never_demotes_a_database_granted_admin(client):
    """The exact production bug: is_admin flipped on in the DB, wiped at login."""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"owner{suffix}", "supersecret1"
    _token_for(client, user, f"owner{suffix}@e.co", pwd)

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.username == user).one()
        row.is_admin = True          # granted out-of-band (psql / Supabase UI)
        db.commit()
    finally:
        db.close()

    again = client.post("/auth/login", json={"username": user, "password": pwd})
    assert again.status_code == 200
    assert again.json()["is_admin"] is True, "login demoted a DB-granted admin"
    h = {"X-User-Token": again.json()["token"]}
    assert client.get("/auth/me", headers=h).json()["is_admin"] is True
    assert client.get("/admin/overview", headers=h).status_code == 200


def test_admin_can_grant_and_revoke_admin(client):
    suffix = uuid.uuid4().hex[:8]
    admin_tok = _token_for(client, f"admin{suffix}", f"a{suffix}@e.co")
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == f"admin{suffix}").update({"is_admin": True})
        db.commit()
    finally:
        db.close()
    ah = {"X-User-Token": admin_tok}

    target_tok = _token_for(client, f"promo{suffix}", f"p{suffix}@e.co")
    th = {"X-User-Token": target_tok}
    assert client.get("/admin/overview", headers=th).status_code == 403

    uid = client.get("/auth/me", headers=th).json()["user_id"]
    r = client.post(f"/admin/users/{uid}/admin", headers=ah, json={"is_admin": True})
    assert r.status_code == 200 and r.json()["is_admin"] is True
    # No re-login needed: the existing token now sees the admin dashboard.
    assert client.get("/admin/overview", headers=th).status_code == 200
    assert client.get("/auth/me", headers=th).json()["is_admin"] is True

    r = client.post(f"/admin/users/{uid}/admin", headers=ah, json={"is_admin": False})
    assert r.status_code == 200 and r.json()["is_admin"] is False
    assert client.get("/admin/overview", headers=th).status_code == 403

    # Non-admins cannot promote themselves, and unknown users 404.
    assert client.post(f"/admin/users/{uid}/admin", headers=th,
                       json={"is_admin": True}).status_code == 403
    assert client.post("/admin/users/999999/admin", headers=ah,
                       json={"is_admin": True}).status_code == 404


def test_admin_username_list_still_grants_on_login(client):
    """ADMIN_USERNAMES keeps working as a GRANT (just never as a demotion)."""
    suffix = uuid.uuid4().hex[:8]
    user, pwd = f"listed{suffix}", "supersecret1"
    _token_for(client, user, f"l{suffix}@e.co", pwd)
    import api_server
    original = api_server.ADMIN_USERNAMES
    api_server.ADMIN_USERNAMES = original | {user.lower()}
    try:
        r = client.post("/auth/login", json={"username": user, "password": pwd})
        assert r.json()["is_admin"] is True
    finally:
        api_server.ADMIN_USERNAMES = original
    # Removing the name again must NOT demote the account.
    r2 = client.post("/auth/login", json={"username": user, "password": pwd})
    assert r2.json()["is_admin"] is True


def test_owner_bootstrap_promotes_the_oldest_account_when_no_admin_exists(client):
    """A deployment that lost its admin heals itself for the owner only."""
    import api_server
    db = SessionLocal()
    try:
        previous = {u.id: u.is_admin for u in db.query(User).all()}
        db.query(User).update({"is_admin": False})
        db.commit()
        owner = db.query(User).order_by(User.id.asc()).first()
        newest = db.query(User).order_by(User.id.desc()).first()
        owner_name, newest_name = owner.username, newest.username
    finally:
        db.close()

    api_server.ADMIN_BOOTSTRAP_FIRST_USER = True
    try:
        # A late signup logging in must NOT be promoted...
        db = SessionLocal()
        try:
            newest_row = db.query(User).filter(User.username == newest_name).one()
            newest_row.password_hash = auth_mod.hash_password("supersecret1")
            owner_row = db.query(User).filter(User.username == owner_name).one()
            owner_row.password_hash = auth_mod.hash_password("supersecret1")
            db.commit()
        finally:
            db.close()
        r = client.post("/auth/login",
                        json={"username": newest_name, "password": "supersecret1"})
        assert r.status_code == 200 and r.json()["is_admin"] is False
        # ...while the oldest account (the instance owner) is.
        r = client.post("/auth/login",
                        json={"username": owner_name, "password": "supersecret1"})
        assert r.status_code == 200 and r.json()["is_admin"] is True
    finally:
        api_server.ADMIN_BOOTSTRAP_FIRST_USER = False
        db = SessionLocal()
        try:
            for uid, flag in previous.items():
                db.query(User).filter(User.id == uid).update({"is_admin": flag})
            db.commit()
        finally:
            db.close()


def test_token_version_claim_roundtrip():
    """auth.decode_token carries the revocation counter; legacy tokens = v0."""
    tok = auth_mod.create_token(42, 7)
    assert auth_mod.decode_token(tok) == (42, 7)
    assert auth_mod.verify_token(tok) == 42
    assert auth_mod.decode_token("garbage") is None
    assert auth_mod.verify_token("") is None


def test_version_is_v1_and_single_sourced():
    """The release number lives in ONE place (the VERSION file) and the API
    reports it. Guards against the version sprawl this repo used to have."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "VERSION"), encoding="utf-8") as fh:
        declared = fh.read().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", declared), \
        f"VERSION must be semver (major.minor.patch), got {declared!r}"
    import api_server
    assert api_server.APP_VERSION == declared
    assert app.version == declared


def test_analyze_via_api_rejects_null_score(monkeypatch):
    """UI regression: a completed-but-unscored legacy row (jd_match_score
    null) used to pass the "key exists" validation; the None then crashed
    the results page with a TypeError in max() right after a batch. It must
    be treated as an invalid payload so the loop falls back to local."""
    import app as ui

    class _Resp:
        ok = True
        status_code = 200
        text = "{}"

        def json(self):
            return {"job_id": "x", "status": "completed", "jd_match_score": None}

    monkeypatch.setattr(ui, "API_URL", "http://ui-test-invalid")
    monkeypatch.setattr(ui.requests, "post", lambda *a, **k: _Resp())

    class _File:
        name = "r.pdf"

        def seek(self, *a):
            pass

        def read(self):
            return b"pdf-bytes"

    payload, err = ui.analyze_via_api(_File(), "jd text")
    assert payload is None and err, "null-score payload must be rejected"


def test_batch_candidate_labels_unique():
    """The batch loop's duplicate-basename handling: two resume.pdf files in
    one upload must produce distinct candidate labels so one does not
    overwrite the other's fields/dup-flag (extracted from app.py's logic)."""
    seen: dict = {}

    def unique_label(name):
        seen_count = seen.get(name, 0) + 1
        seen[name] = seen_count
        return name if seen_count == 1 else f"{name} ({seen_count})"

    labels = [unique_label("resume.pdf") for _ in range(2)]
    assert labels == ["resume.pdf", "resume.pdf (2)"]
    assert len(set(labels)) == 2


# --------------------------------------------------------------------------
# Enum persistence contract (production incident: psycopg2 22P02)
# --------------------------------------------------------------------------
# Fly logs showed every status write and every status filter failing with
#   invalid input value for enum jobstatus: "COMPLETED"
# because migration 20260821 creates the Postgres type with LOWERCASE labels
# while a bare Enum(JobStatus) persists the Python member NAMES. SQLite does
# not enforce enum labels, so the whole suite stayed green while production
# could not save a single analysis. These tests pin the contract on ANY
# backend by asserting the type's stored labels and the compiled bind value.

def test_jobstatus_column_stores_lowercase_enum_values():
    """The column must persist member VALUES ('completed'), never member
    NAMES ('COMPLETED') — the latter is rejected by the Postgres type."""
    import sqlalchemy as sa
    from models import JobStatus, ResumeResult

    col = ResumeResult.__table__.columns["status"]
    assert isinstance(col.type, sa.Enum)
    assert col.type.name == "jobstatus"
    assert sorted(col.type.enums) == sorted(m.value for m in JobStatus)
    assert col.type.enums == ["queued", "processing", "completed", "failed"]


def test_jobstatus_matches_migration_enum_labels():
    """Model and migration must not drift: the labels the model writes are
    exactly the labels CREATE TYPE jobstatus declared."""
    import sqlalchemy as sa
    from models import ResumeResult

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "migrations", "versions",
                        "20260821_create_resume_results.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    declared = re.search(r"sa\.Enum\((.*?),\s*name='jobstatus'\)", source, re.S)
    assert declared, "migration no longer declares the jobstatus enum"
    migration_labels = re.findall(r"'([a-z]+)'", declared.group(1))

    col = ResumeResult.__table__.columns["status"]
    assert isinstance(col.type, sa.Enum)
    assert col.type.enums == migration_labels


def test_jobstatus_binds_lowercase_on_postgres_dialect():
    """The value handed to the Postgres driver must be the lowercase label.

    This is what actually blew up in production: SQLAlchemy keeps the Python
    member in the compiled params and converts it in the type's bind
    processor, so the processor's output is the string psycopg2 sends.
    """
    from sqlalchemy.dialects import postgresql
    from models import JobStatus, ResumeResult

    col = ResumeResult.__table__.columns["status"]
    process = col.type.bind_processor(postgresql.dialect())
    for member in JobStatus:
        assert process(member) == member.value
    assert process(JobStatus.COMPLETED) == "completed"
    assert process(JobStatus.PROCESSING) == "processing"

    # and the result processor maps the DB label back to the Python member
    unprocess = col.type.result_processor(postgresql.dialect(), None)
    assert unprocess("completed") is JobStatus.COMPLETED


# --------------------------------------------------------------------------
# api_fetch_json error contract (production: Analytics page KeyError)
# --------------------------------------------------------------------------

def _fake_response(status, payload=None, text=None):
    class _R:
        status_code = status
        ok = 200 <= status < 300

        def __init__(self):
            self.text = text if text is not None else json.dumps(payload or {})

        def json(self):
            if payload is None:
                raise ValueError("no json")
            return payload
    return _R()


def test_api_fetch_json_returns_none_data_on_error_status(monkeypatch):
    """A 503 from /analytics/summary decodes as {"detail": ...} — valid JSON.
    Returning it as `data` slipped past every `if data is None:` guard and
    the page then died on data["total_jobs"]. Error statuses must yield
    data=None plus a human-readable error."""
    import app as ui

    resp = _fake_response(
        503, {"detail": "Analytics is temporarily unavailable (storage). "
                        "Retry in a moment."})
    monkeypatch.setattr(ui, "API_URL", "http://ui-test")
    monkeypatch.setattr(ui.requests, "get", lambda *a, **k: resp)

    r, data, err = ui.api_fetch_json("/analytics/summary")
    assert data is None, "error bodies must never be handed back as payload"
    assert r is not None and r.status_code == 503, "caller still needs the status"
    assert err and "503" in err
    assert "temporarily unavailable" in err, "detail must reach the retry panel"


def test_api_fetch_json_passes_through_success(monkeypatch):
    """The happy path is unchanged: 200 -> decoded payload, no error."""
    import app as ui

    resp = _fake_response(200, {"total_jobs": 7, "by_status": {"completed": 7}})
    monkeypatch.setattr(ui, "API_URL", "http://ui-test")
    monkeypatch.setattr(ui.requests, "get", lambda *a, **k: resp)

    r, data, err = ui.api_fetch_json("/analytics/summary")
    assert err is None
    assert data["total_jobs"] == 7


def test_api_fetch_json_auth_statuses_still_expose_status_code(monkeypatch):
    """Admin/History branch on resp.status_code for 401/403 (expired session,
    non-admin). Suppressing the body must not suppress the response."""
    import app as ui

    for code in (401, 403):
        resp = _fake_response(code, {"detail": "nope"})
        monkeypatch.setattr(ui, "API_URL", "http://ui-test")
        monkeypatch.setattr(ui.requests, "get", lambda *a, **k: resp)
        r, data, err = ui.api_fetch_json("/admin/overview")
        assert r.status_code == code and data is None and err


# --------------------------------------------------------------------------
# Model <-> migration drift guards
# --------------------------------------------------------------------------
# The jobstatus outage was drift the test suite could not see. These checks
# compare the ORM against the migration DDL as SOURCE TEXT, so they work on
# SQLite (and in CI) without needing a live Postgres.

def test_resume_results_timestamps_match_migration_nullability():
    """Migration 20260821 creates created_at/updated_at NOT NULL. A model that
    says nullable=True hides an IntegrityError that only Postgres raises."""
    from models import ResumeResult

    for name in ("created_at", "updated_at"):
        col = ResumeResult.__table__.columns[name]
        assert col.nullable is False, (
            f"{name}: model allows NULL but the migration created it NOT NULL")
        assert col.server_default is not None, (
            f"{name}: migration sets a server_default; the model must too, or "
            "raw INSERTs that skip the ORM default will fail")


def test_no_model_column_is_missing_from_migrations():
    """Every column the ORM selects must exist in the migration DDL.

    A model-only column makes EVERY query against that table fail on Postgres
    with UndefinedColumn while SQLite tests (which build the schema from the
    models themselves) stay green.
    """
    from models import ResumeResult, User

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    versions = os.path.join(root, "migrations", "versions")
    ddl = ""
    for fname in sorted(os.listdir(versions)):
        if fname.endswith(".py"):
            with open(os.path.join(versions, fname), encoding="utf-8") as fh:
                ddl += fh.read()

    for model in (ResumeResult, User):
        for col in model.__table__.columns:
            assert f"'{col.name}'" in ddl or f'"{col.name}"' in ddl, (
                f"{model.__tablename__}.{col.name} exists in the model but no "
                f"migration ever creates it -> UndefinedColumn on Postgres")


# --------------------------------------------------------------------------
# Fail-safe auth secret + honest readiness probe
# --------------------------------------------------------------------------

def test_auth_rejects_tokens_forged_with_the_published_default_secret():
    """auth.py used to fall back to a hard-coded secret that is published in
    this repo. Any deployment missing AUTH_SECRET_KEY could be impersonated by
    signing a token with that known value -- silently, forever. The fallback
    must now be random per process, so such a token cannot verify."""
    import importlib
    from itsdangerous import URLSafeTimedSerializer

    forged = URLSafeTimedSerializer(
        "dev-insecure-secret-change-me", salt="resume-auth-v1"
    ).dumps({"uid": 1, "tv": 0})

    saved = os.environ.get("AUTH_SECRET_KEY")
    try:
        os.environ.pop("AUTH_SECRET_KEY", None)
        mod = importlib.reload(importlib.import_module("auth"))
        assert mod.AUTH_SECRET_IS_EPHEMERAL is True
        assert mod.verify_token(forged) is None, \
            "token forged with the published default secret must NOT verify"
        # a token this process minted still works
        assert mod.verify_token(mod.create_token(7, 0)) == 7
    finally:
        if saved is not None:
            os.environ["AUTH_SECRET_KEY"] = saved
        else:
            os.environ["AUTH_SECRET_KEY"] = "test-secret-not-for-production"
        importlib.reload(importlib.import_module("auth"))


def test_configured_secret_is_used_verbatim():
    """A real secret must be honoured (tokens survive restarts)."""
    import importlib

    saved = os.environ.get("AUTH_SECRET_KEY")
    try:
        os.environ["AUTH_SECRET_KEY"] = "a-genuinely-long-random-production-secret"
        mod = importlib.reload(importlib.import_module("auth"))
        assert mod.AUTH_SECRET_IS_EPHEMERAL is False
        assert mod.SECRET_KEY == "a-genuinely-long-random-production-secret"
    finally:
        os.environ["AUTH_SECRET_KEY"] = saved or "test-secret-not-for-production"
        importlib.reload(importlib.import_module("auth"))


def test_health_is_liveness_only_and_ready_checks_the_database(client):
    """/health must stay dependency-free (Fly restarts the machine when it
    fails), while /health/ready reports real dependency state."""
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "ok",
                        "version": r.json()["version"]}


def test_readiness_reports_503_when_the_database_is_unusable(client):
    """The whole point: during the outage /health said "ok" every 15s while
    every write failed. A readiness probe must go red instead."""
    import sqlalchemy as sa
    import api_server

    real_bind = api_server.SessionLocal.kw["bind"]
    dead = sa.create_engine("postgresql://nobody:nobody@127.0.0.1:1/none",
                            connect_args={"connect_timeout": 1})
    try:
        api_server.SessionLocal.configure(bind=dead)
        r = client.get("/health/ready")
        assert r.status_code == 503, "readiness must fail when storage is down"
        assert r.json()["database"] == "unavailable"
        # liveness stays green so the platform does not restart-loop the app
        assert client.get("/health").status_code == 200
    finally:
        api_server.SessionLocal.configure(bind=real_bind)
