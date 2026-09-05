# 🎯 ResumeRank — Engineering Audit & Verification Report

**To:** FEMZYKENTLTD / Olufemi Benua Keripe (FEMZY)
**Document type:** Historical engineering notes, not an independent audit or certification
**Date:** August 31, 2026
**Subject:** Repository ownership handover, CI failure root-cause analysis, README verification audit
**Scope:** commit `910fcf6` on `main` (failng run: [Verify & Deploy #33447066825](https://github.com/FEMZYKENTLTD/Resume-Screening-Classifier/actions/runs/33447066825))

> **Historical document.** This preserves earlier maintenance observations for the dated
> scopes below, including the September 2 addendum. Those claims have not all been reverified
> in this update and are not current deployment, security, or model-quality guarantees.
> See the [README](../README.md#testing-and-verification) for the latest scoped verification
> results and limitations. This is not an independent security or hiring-validity audit.

---

## 🏛️ 1. Ownership & Executive Summary

This section records earlier maintenance of the **Resume-Screening-Classifier** (`ResumeRank`) repository.

**Verdict at handover: 🔴 CI RED → 🟢 FIXED.** The repository was **not** deployable: the
`Verify & Deploy Full Stack` workflow failed in the `verify` job (`pytest -q` exit code 2),
which correctly blocked all three deploy jobs. This report documents the root causes, the
repairs, and a full verification of every claim in the README against the actual code.

### Repairs delivered in this pass

| # | Defect | Root cause | Fix |
|---|--------|-----------|-----|
| 1 | `pytest` aborted at collection (exit 2) — **the CI failure** | `api_server.py` used `class Credentials(auth.BaseModel)` but `auth.py` never re-exported pydantic's `BaseModel`; import-time `AttributeError` | `from pydantic import BaseModel` in `api_server.py` (request models belong to the API layer) |
| 2 | App crashed at startup / every `/metrics` scrape | `api_server.py` called `monitoring.init_metrics()`, `monitoring.generate_metrics()`, `monitoring.record_request()` — none existed in `monitoring.py` | Implemented `init_metrics()` + `record_request()`; `/metrics` now returns a proper Prometheus `Response` via `metrics_response()` |
| 3 | No API request metrics (README promised them) | The documented "request counters/latency via middleware" had been deleted | Added ASGI middleware recording `method / route-template / status / latency` with bounded label cardinality |
| 4 | Signup accepted any credentials | Pydantic models had no constraints (tests expect 422 on short username/password) | `SignupRequest`: username ≥ 3, password ≥ 8, email ≤ 100; **login deliberately lenient** so wrong passwords stay `401`, not `422` |
| 5 | Analytics page crashed (`KeyError: 'score_histogram'`) | UI/API contract drift — endpoint no longer returned the histogram | `/analytics/summary` + `/admin/trends` expose `score_histogram` (ten 10-wide buckets) |
| 6 | Admin page crashed (`KeyError: 'by_status'`, `'last_active'`) | Same drift on `/admin/overview` + `/admin/users` | Overview: `by_status`, `jobs_last_7d`, `avg_match_score`. Users: per-user `completed` / `failed` / `last_active`, computed in a single scan (N+1 query removed) |
| 7 | Node.js 20 deprecation warning in Actions | `actions/checkout@v4`, `actions/setup-python@v5` target Node 20 (removed from runners 2026-09-16) | Bumped to `checkout@v7`, `setup-python@v7`; pinned `flyctl-actions/setup-flyctl@v1` (was floating `@master`). **✅ Resolved:** the Node 24 action bumps are live in `.github/workflows/deploy.yml`, so the `docs/deploy.yml.node24` reference copy was deleted in v1.0. One cosmetic delta remains and needs a human with `workflows` permission: replace the two `pip install -r requirements.txt` / `pip install pytest httpx` lines with `pip install -r requirements.txt -r requirements-dev.txt` to pin CI test tooling |

---

## 🧪 2. Verification Results (all executed in this sandbox)

| Gate | Command | Result |
|------|---------|--------|
| Compile | `python -m compileall -q .` | ✅ clean |
| Unit + integration suite | `pytest tests/ -q` (SQLite, eager Celery) | ✅ **30 passed, 1 skipped** — with scikit-learn 1.9.0 + spaCy 3.8.16 installed; the single skip is the spaCy-model NER test (model wheel download blocked by this sandbox's network — the regex fallback path is covered by `test_extract_fields_reports_method`) |
| — bare-CI parity | no ML extras | ✅ 28 passed, 3 auto-skips (optional ML tests) — exit 0 |
| ML artifact compatibility | `test_ml_classifier_artifact_loads_and_predicts` | ✅ committed `models/role_classifier.joblib` loads & predicts on the pinned scikit-learn 1.9.0 (samples ≥ 48, expected labels present) |
| Migrations | `alembic upgrade head` on fresh SQLite | ✅ 7 revisions, **single linear head**, seed data lands |
| Live E2E | `scripts/verify_ui_live.py` against real `uvicorn` + `streamlit` | ✅ **21 passed, 0 failed** (real logins, PDF through the full pipeline, AppTest on every page incl. 401/403 gating) |

**Key point:** the live E2E caught defects #5 and #6 that the unit suite (and the previous
audit in this file) could not see — the dashboards were rendering exceptions against the
current API. That is why the harness is run against a *real* stack, and why it stays in the
verification plan.

---

## 📋 3. README Verification Matrix

| README claim | Status |
|--------------|--------|
| PDF + DOCX parsing (PyMuPDF / python-docx) | ✅ verified by tests |
| Match score 0–100 % keyword overlap | ✅ verified by tests |
| Optional semantic blending 0.65/0.35 + skill gaps | ✅ verified (stub-model test; heavy deps optional by design) |
| Field extraction (name/email/phone/experience/education/orgs) | ✅ verified by tests + live E2E (`Adaeze Obi`) |
| Trained role classifier artifact + keyword fallback | ✅ artifact loads & predicts on pinned sklearn |
| Smart duplicate detection (resume+JD hash, unique index) | ✅ verified by tests |
| bcrypt + signed expiring tokens; admin gate anon 401 / non-admin 403 | ✅ verified by tests + live E2E |
| Alembic single linear head, auto-applied on deploy | ✅ verified (7 revisions, clean upgrade) |
| `/metrics` on API and worker; provisioned Grafana board | ✅ now true (was broken — repair #2/#3); scrape targets consistent with `docker-compose.yml` / `WORKER_METRICS_PORT` |
| `docker compose up` → 7 services | ✅ compose file matches (db, redis, api, worker, streamlit, prometheus, grafana) |
| Demo kit (4 resumes + JD) | ✅ present in `demo/` |
| **"Requests return ~50 ms (202 Accepted + job_id)" / enqueue→worker diagram** | ⚠️ **stale — corrected.** The API is synchronous direct processing (`POST /single_analyze` returns the completed result); the Celery lane still ships as the optional async path |
| **"pytest → 31 passed"** | ⚠️ **corrected.** 31 tests exist; 31/31 pass with all ML extras, 30/1 with sklearn only (spaCy model unavailable offline), 28/3 on bare CI |
| `verify_ui_live.py` → 21 passed | ✅ now true (was failing — repairs #5/#6) |

---

## 🚀 4. Ongoing Ownership Plan

1. **Keep the E2E harness honest** — run `scripts/verify_ui_live.py` on the running stack
   after any API-shape change; the unit suite alone missed two contract breaks.
2. **CI/CD** — Actions now run on Node 24 (`checkout@v7`, `setup-python@v7`); keep action
   majors current. Watch the 2026-09-16 Node 20 removal — this repo is compliant.
3. **Retraining cadence** — regenerate `models/role_classifier.joblib` via
   `training/train_role_classifier.py` as the corpus grows; verify with the two ML tests.
4. **Deploy hygiene** — Fly secrets via `fly secrets set` (never TOML interpolation);
   Render deploy hook unchanged. Deploy jobs were not exercised here (they require live
   `FLY_API_TOKEN` / `RENDER_API_KEY` secrets and push-to-main).

---
*Historical maintenance notes; see the dated scope above.*

---

## 🔟 5. Addendum — v1.0 release audit

**Date:** September 2, 2026 · **Scope:** branch `arena/01a06332-resume-screening-classifier`
(the v1.0 release commit). Everything here was re-measured in a clean environment, not
carried over from the report above.

### Defects found and fixed in this pass

| # | Defect (as reported by the owner) | Root cause | Fix |
|---|---|---|---|
| 1 | "The site doesn't log out" | Session tokens were stateless and un-revocable; the cookie-clearing component was destroyed by `st.rerun()` before its script could run; `st.context.cookies` still held the old token on the next run, so the restore path signed the user back in | `users.token_version` + `POST /auth/logout` (server-side revocation), deletion rendered on a page that survives, `logged_out` flag blocks cookie restore |
| 2 | "Stuck on the login page" | A single 3 s `/health` probe against a cold API flipped the UI into the legacy env-credential login, which database accounts can never pass | Probe retried ×3, cached 30 s, sticky once seen up; `ALLOW_LEGACY_LOGIN=0` disables the fallback; legacy mode also gained the **Log out** button it never had |
| 3 | "My admin account doesn't reflect as admin" | `/auth/login` mirrored `ADMIN_USERNAMES` onto `users.is_admin`, demoting every DB-granted admin on sign-in (reproduced: `is_admin` 1 → 0) | Grant-only sync (`ADMIN_STRICT_SYNC=1` to opt out), owner bootstrap, `POST /admin/users/{id}/admin` + Roles & Access UI, `scripts/grant_admin.py`, live `/auth/me` refresh every 30 s |
| 4 | Stale CI handoff | The Node 24 workflow fix had been applied, but a 109-line duplicate (`docs/deploy.yml.node24`) and its instructions lingered | Duplicate deleted; the single remaining one-line CI improvement is documented inline in `requirements-dev.txt` (workflow edits need `workflows` token permission) |
| 5 | README drift | Undocumented `/auth/me`; stale counts (tests, live checks, Alembic revisions); duplicated `training/` entry in the file tree; broken LinkedIn markdown link; inconsistent release labels | README corrected end-to-end and **relabelled to a single version: v1.0** |

### Verification (all executed on this branch)

| Gate | Command | Result |
|------|---------|--------|
| Compile | `python -m compileall -q .` | ✅ clean |
| Unit + integration, with extras | `pytest -q` (scikit-learn + spaCy + psycopg2) | ✅ **88 passed, 1 skipped** (skip = pretrained spaCy weights, download blocked offline) |
| Unit + integration, bare | `pytest -q` (no optional extras) | ✅ **79 passed, 10 auto-skips** — 89 tests collected |
| Migrations | `alembic upgrade head` on a fresh database | ✅ **8 revisions, single linear head**, `users.token_version` created |
| Live E2E | `scripts/verify_ui_live.py` against real `uvicorn` + `streamlit` | ✅ **32 passed, 0 failed** (was 21 — added logout revocation, role stability and UI logout-button checks) |
| Model artifact | `models/role_classifier.joblib` metadata | ✅ 9 labels · 619 samples · held-out accuracy **1.0 over 141 docs** — matches the README claim |

### README claim spot-checks

| Claim | Status |
|---|---|
| 9 role families · 619 training docs · 100% over 141 held-out docs | ✅ read back from the shipped artifact metadata |
| `docker compose up` → 7 services | ✅ db · redis · api · worker · streamlit · prometheus · grafana |
| Every test name cited in the README exists | ✅ all resolve to `tests/test_core.py` |
| Every documented endpoint exists, and every endpoint is documented | ✅ 15 routes reconciled both ways |
| Alembic single linear head, auto-applied on deploy | ✅ verified (`wait-for-db.sh` + Fly `release_command`) |

*End of historical v1.0 release notes.*
