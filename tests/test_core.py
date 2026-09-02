"""
End-to-end + unit tests for the Resume Screening Classifier.

Runs the full FastAPI -> Celery (eager mode) -> SQLAlchemy -> SQLite flow
without needing Postgres or Redis, so it can run in CI in seconds.
Semantic matching is tested with a stub embedding model (no torch needed).
"""

import io
import json
import os
import sys
import uuid
import zipfile

# Point the app at a throwaway SQLite file BEFORE importing app modules.
os.environ["DATABASE_URL"] = "sqlite:////tmp/test_resume_classifier.db"
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
from api_server import app  # noqa: E402
from database import engine  # noqa: E402
from extractors import extract_fields  # noqa: E402
from models import Base  # noqa: E402
from roles import classify_role, classify_role_keywords, classify_role_with_method  # noqa: E402
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
    os.unlink("/tmp/test_resume_classifier.db")


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
    skills = extract_skills("Experience with Python, AWS and Kubernetes.")
    assert skills == {"Python", "Aws", "Kubernetes"}


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

    monkeypatch.setattr(api_server, "overlap_score",
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
