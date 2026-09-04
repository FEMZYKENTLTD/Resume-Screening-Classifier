"""
Authentication helpers for the Resume Screening Classifier.

- Passwords: bcrypt hashes (never stored in plaintext, never committed).
- Sessions: stateless signed tokens (itsdangerous), no server-side store
  needed; tokens expire after TOKEN_MAX_AGE_DAYS.

Set AUTH_SECRET_KEY in production (.env.example shows where).
"""

import logging
import os
import secrets

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger("resumerank.auth")

# The hard-coded fallback that used to live here was a silent, critical hole:
# the value is published in this repo, so ANYONE could mint
# `create_token(<any user id>)` and be that user -- including an admin --
# against any deployment where AUTH_SECRET_KEY was unset, empty, or still the
# placeholder from .env.example. Nothing in the logs or the UI would ever show
# it; the deployment simply looks fine until it is abused.
#
# Fail SAFE instead of fail OPEN: when no usable secret is configured we sign
# with a random per-process key. Forged tokens made with the published default
# are rejected outright, and the loud startup log below says exactly what to
# set. The cost of the fallback is that sessions do not survive a restart --
# which is a visible, harmless nuisance, unlike a silent auth bypass.
_INSECURE_DEFAULTS = {
    "",
    "dev-insecure-secret-change-me",
    "change-me-to-a-long-random-secret",
    "test-secret-not-for-production",
    "changeme",
    "secret",
}

_configured = (os.environ.get("AUTH_SECRET_KEY") or "").strip()
AUTH_SECRET_IS_EPHEMERAL = _configured.lower() in _INSECURE_DEFAULTS

if AUTH_SECRET_IS_EPHEMERAL:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.critical(
        "AUTH_SECRET_KEY is %s -- signing sessions with a RANDOM per-process "
        "key. Tokens are invalidated on every restart/redeploy (users will be "
        "logged out). Set a long random AUTH_SECRET_KEY to fix this: "
        "fly secrets set AUTH_SECRET_KEY=\"$(python -c 'import secrets;"
        "print(secrets.token_urlsafe(48))')\" --app <your-app>",
        "not set" if not _configured else "a well-known placeholder value",
    )
else:
    SECRET_KEY = _configured

TOKEN_MAX_AGE_DAYS = int(os.environ.get("TOKEN_MAX_AGE_DAYS", "7"))

_serializer = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(SECRET_KEY, salt="resume-auth-v1")
    return _serializer


# bcrypt hard-rejects secrets longer than 72 BYTES (it silently truncated in
# older releases; 5.x raises ValueError). The signup schema allows 128 chars,
# and non-ASCII characters cost several bytes each, so unbounded input made
# /auth/signup return a 500. Truncate on a byte boundary, identically on both
# the hash and verify paths so long passwords stay usable.
BCRYPT_MAX_BYTES = 72


def _bcrypt_secret(password: str) -> bytes:
    raw = (password or "").encode("utf-8")
    if len(raw) <= BCRYPT_MAX_BYTES:
        return raw
    # Never split a multi-byte character in half.
    return raw[:BCRYPT_MAX_BYTES].decode("utf-8", "ignore").encode("utf-8")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_secret(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_secret(password),
                              (password_hash or "").encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, token_version: int = 0) -> str:
    """Signed token identifying a user.

    ``token_version`` mirrors ``users.token_version``. Logging out bumps that
    column, which instantly invalidates every token minted before the bump —
    that is what makes "Log out" authoritative on the SERVER, instead of
    relying on the browser actually dropping its cookie (it often did not,
    which is why the UI kept resurrecting a session after logout).
    """
    return _get_serializer().dumps({"uid": user_id, "tv": int(token_version or 0)})


def decode_token(token: str):
    """Return ``(user_id, token_version)`` for a valid token, else ``None``.

    Tokens minted before token versioning existed carry no ``tv`` claim; they
    are read as version 0 so old sessions keep working across the upgrade.
    """
    if not token:
        return None
    try:
        data = _get_serializer().loads(
            token, max_age=TOKEN_MAX_AGE_DAYS * 24 * 3600
        )
        return int(data["uid"]), int(data.get("tv", 0) or 0)
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError,
            AttributeError):
        return None


def verify_token(token: str):
    """Return the user_id for a valid, unexpired token, else None.

    Signature-level check only — it cannot see the revocation counter. API
    code should prefer :func:`decode_token` plus a ``token_version`` compare
    (``api_server._current_user_id`` does exactly that).
    """
    decoded = decode_token(token)
    return None if decoded is None else decoded[0]
