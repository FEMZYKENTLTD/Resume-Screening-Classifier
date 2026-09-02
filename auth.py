"""
Authentication helpers for the Resume Screening Classifier.

- Passwords: bcrypt hashes (never stored in plaintext, never committed).
- Sessions: stateless signed tokens (itsdangerous), no server-side store
  needed; tokens expire after TOKEN_MAX_AGE_DAYS.

Set AUTH_SECRET_KEY in production (.env.example shows where).
"""

import os

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "dev-insecure-secret-change-me")
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
