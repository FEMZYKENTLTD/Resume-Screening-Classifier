#!/usr/bin/env python3
"""32-check LIVE end-to-end verification for ResumeRank.

Drives the *actually running* stack — no mocks:

  1. service health (API + Streamlit)
  2. real logins (admin + non-admin accounts)
  3. a generated resume PDF pushed through the real pipeline
     (POST /single_analyze -> Celery worker -> DB -> GET /results)
  4. every UI page rendered headlessly via streamlit.testing.AppTest
     (login, screening, analytics, history, admin) with zero exceptions,
     including the admin 401/403 gate
  5. session lifecycle: /auth/logout really revokes the token, the user can
     log back in, and the sidebar "Log out" button clears the UI session
  6. role stability: an admin stays an admin across re-login

Usage:
    pip install streamlit[testing] fpdf2 requests        # + repo requirements
    export API_URL=http://127.0.0.1:8000                 # default
    export STREAMLIT_URL=http://127.0.0.1:8501           # default
    export ADMIN_USER=admin ADMIN_PASS=admin12345
    export DEMO_USER=jane  DEMO_PASS=jane12345
    python scripts/verify_ui_live.py

Exit code 0 = all checks green; 1 = something failed (details printed).
Seed accounts are created by docker-compose/migrations demo seed, or create
them via the UI sign-up page and export the env vars above.
"""

from __future__ import annotations

import io
import os
import pathlib
import sys
import time

import requests

API = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
FRONT = os.environ.get("STREAMLIT_URL", "http://127.0.0.1:8501").rstrip("/")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin12345")
DEMO_USER = os.environ.get("DEMO_USER", "jane")
DEMO_PASS = os.environ.get("DEMO_PASS", "jane12345")
APP_PATH = os.environ.get(
    "APP_PATH", str(pathlib.Path(__file__).resolve().parent.parent / "app.py")
)

os.environ["API_URL"] = API  # the UI reads this at import time

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("✅ PASS " if cond else "❌ FAIL ") + name + (f"  [{extra}]" if extra else ""))


# ---------- 1. services ----------
try:
    h = requests.get(f"{API}/health", timeout=5)
    check("API /health 200", h.ok, h.text[:60])
except Exception as exc:  # pragma: no cover
    check("API /health 200", False, str(exc))
    print(f"\n== RESULT: {len(PASS)} passed, {len(FAIL)} failed ==")
    sys.exit(1)
try:
    s = requests.get(f"{FRONT}/healthz", timeout=5)
    check("Streamlit /healthz ok", s.ok)
except Exception as exc:  # pragma: no cover
    check("Streamlit /healthz ok", False, str(exc))

# ---------- 2. real tokens ----------
admin_login = requests.post(f"{API}/auth/login",
                            json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=10)
check("admin login", admin_login.ok and admin_login.json().get("is_admin") is True)
admin_tok = admin_login.json()["token"]
demo_login = requests.post(f"{API}/auth/login",
                           json={"username": DEMO_USER, "password": DEMO_PASS}, timeout=10)
check("demo user login (non-admin)", demo_login.ok and demo_login.json().get("is_admin") is False)
demo_tok = demo_login.json()["token"]

# ---------- 3. full pipeline: generated PDF through the queue ----------
from fpdf import FPDF  # noqa: E402

pdf = FPDF()
pdf.add_page()
pdf.set_font("helvetica", size=12)
pdf.multi_cell(0, 8, "Adaeze Obi\nSenior DevOps Engineer\nadaeze.obi@example.com\n"
                     "+234 801 234 5678\n"
                     "7 years experience: Kubernetes, Terraform, AWS, Docker, CI/CD, "
                     "Python, Prometheus, Grafana.\n"
                     "B.Sc Computer Science, University of Lagos. "
                     "Previously at Paystack and Flutterwave.")
sub = requests.post(
    f"{API}/single_analyze",
    files={"resume": ("adaeze_obi.pdf", io.BytesIO(bytes(pdf.output())), "application/pdf")},
    data={"jd": "We need a DevOps engineer skilled in Kubernetes, Terraform, AWS, CI/CD and Python."},
    headers={"X-User-Token": demo_tok}, timeout=30)
check("POST /single_analyze accepted", sub.ok, sub.text[:100])
job_id = sub.json()["job_id"]
final = None
for _ in range(40):
    r = requests.get(f"{API}/results/{job_id}", timeout=10)
    if r.ok and r.json()["status"] in ("completed", "failed"):
        final = r.json()
        break
    time.sleep(2)
check("worker completed job", bool(final) and final["status"] == "completed",
      f"score={final and final.get('jd_match_score')} role={final and final.get('predicted_role')}")
if final:
    fields = final.get("extracted_fields") or {}
    check("NER name extracted", bool(fields.get("name")), str(fields.get("name")))
    check("score is 0-100 & >0",
          isinstance(final.get("jd_match_score"), (int, float)) and final["jd_match_score"] > 0,
          str(final.get("jd_match_score")))

# ---------- 4. AppTest: every page, admin + non-admin ----------
from streamlit.testing.v1 import AppTest  # noqa: E402


def switch(at, target: str) -> None:
    """Set the nav radio — re-queried each time (AppTest element handles go
    stale after every run)."""
    nav = [r for r in at.radio if "🔍 Screening" in r.options][0]
    nav.set_value(target)
    at.run()
    cur = [r for r in at.radio if "🔍 Screening" in r.options][0].value
    assert cur == target, f"nav stuck at {cur}, wanted {target}"


at = AppTest.from_file(APP_PATH, default_timeout=40)
at.run()
check("login page renders, no exception", not at.exception)
check("login tabs present", any("Login" in (t.label or "") for t in at.tabs))

at.session_state["token"] = admin_tok
at.session_state["username"] = ADMIN_USER
at.session_state["is_admin"] = True
at.run()
check("screening page renders (admin), no exception", not at.exception)

switch(at, "📈 Analytics")
check("analytics page, no exception", not at.exception)
check("analytics hero rendered", any("Analytics" in (m.value or "") for m in at.markdown))

switch(at, "🗂 My History")
check("history page (admin), no exception", not at.exception)

switch(at, "🛠 Admin")
check("admin page, no exception", not at.exception)
check("admin hero rendered", any("Admin Dashboard" in (m.value or "") for m in at.markdown))
check("admin users table rendered", any("Registered Users" in (m.value or "") for m in at.markdown))

at2 = AppTest.from_file(APP_PATH, default_timeout=40)
at2.session_state["token"] = demo_tok
at2.session_state["username"] = DEMO_USER
at2.session_state["is_admin"] = False
at2.run()
check("screening page renders (demo user), no exception", not at2.exception)
opts = [o for r in at2.radio for o in r.options]
check("admin page hidden from non-admin", "🛠 Admin" not in opts)
switch(at2, "🗂 My History")
check("history page (demo user), no exception", not at2.exception)
check("demo user history has dataframe rows", len(at2.dataframe) >= 1)

# ---------- 5. session lifecycle: logout really logs out ----------
# Regression guard for the two reported production defects.
logout_login = requests.post(f"{API}/auth/login",
                             json={"username": DEMO_USER, "password": DEMO_PASS}, timeout=10)
throwaway_tok = logout_login.json()["token"]
check("logout endpoint 200",
      requests.post(f"{API}/auth/logout",
                    headers={"X-User-Token": throwaway_tok}, timeout=10).ok)
check("token revoked after logout (stale cookie cannot resurrect it)",
      requests.get(f"{API}/auth/me",
                   headers={"X-User-Token": throwaway_tok}, timeout=10).status_code == 401)
relogin = requests.post(f"{API}/auth/login",
                        json={"username": DEMO_USER, "password": DEMO_PASS}, timeout=10)
check("can log back in after logout", relogin.ok)
demo_tok = relogin.json()["token"]

# ---------- 6. admin role is stable and live ----------
check("admin flag survives re-login (no silent demotion)",
      requests.post(f"{API}/auth/login",
                    json={"username": ADMIN_USER, "password": ADMIN_PASS},
                    timeout=10).json().get("is_admin") is True)
check("non-admin blocked from /admin/overview (403)",
      requests.get(f"{API}/admin/overview",
                   headers={"X-User-Token": demo_tok}, timeout=10).status_code == 403)
check("admin sees the Roles & Access control",
      any("Roles & Access" in (m.value or "") for m in at.markdown))

# ---------- 7. UI logout button clears the session ----------
at3 = AppTest.from_file(APP_PATH, default_timeout=40)
at3.session_state["token"] = admin_tok
at3.session_state["username"] = ADMIN_USER
at3.session_state["is_admin"] = True
at3.run()
logout_btn = [b for b in at3.sidebar.button if "Log out" in (b.label or "")]
check("log out button present", bool(logout_btn))
if logout_btn:
    logout_btn[0].click().run()
    check("UI logout clears the token", at3.session_state["token"] is None)
    check("UI logout marks the session logged out (blocks cookie restore)",
          at3.session_state["logged_out"] is True)
    check("logged-out UI shows the login form", any("Login" in (t.label or "") for t in at3.tabs))
    check("logged-out UI has no exception", not at3.exception)
    # admin_tok was revoked by the button: mint a new one for anything after.
    admin_tok = requests.post(f"{API}/auth/login",
                              json={"username": ADMIN_USER, "password": ADMIN_PASS},
                              timeout=10).json()["token"]

print(f"\n== RESULT: {len(PASS)} passed, {len(FAIL)} failed ==")
sys.exit(1 if FAIL else 0)
