"""
Shared pytest setup.

conftest.py is imported by pytest BEFORE any test module, which is the only
reliable place to set DATABASE_URL: database.py builds its engine at import
time, so the variable must exist before `import api_server` runs.

Why a unique file per run
-------------------------
The suite used to hard-code sqlite:////tmp/test_resume_classifier.db. That
single shared file survived between runs, so a schema change or a row left by
a previous run could poison the next one — producing failures that vanished
after a manual `rm`, which is the worst kind of flake to debug. Each run now
gets its own database, removed on exit.

Override by exporting DATABASE_URL yourself (e.g. to test against Postgres).
"""

import os
import shutil
import tempfile

_TMPDIR = None

if not os.environ.get("DATABASE_URL"):
    _TMPDIR = tempfile.mkdtemp(prefix="resumerank-tests-")
    os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"

# Deterministic, non-secret defaults so tests never depend on a developer's
# local .env — and never accidentally pick up production credentials.
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-not-for-production")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("ADMIN_USERNAMES", "admin")
# Keep optional integrations off unless a test explicitly enables them.
os.environ.setdefault("ENABLE_SEMANTIC", "0")


def pytest_sessionfinish(session, exitstatus):
    """Remove the throwaway database directory created for this run."""
    if _TMPDIR:
        shutil.rmtree(_TMPDIR, ignore_errors=True)
