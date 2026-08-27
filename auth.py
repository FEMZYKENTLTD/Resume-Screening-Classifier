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


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int) -> str:
    """Signed token identifying a user (stateless)."""
    return _get_serializer().dumps({"uid": user_id})


def verify_token(token: str):
    """Return the user_id for a valid, unexpired token, else None."""
    if not token:
        return None
    try:
        data = _get_serializer().loads(
            token, max_age=TOKEN_MAX_AGE_DAYS * 24 * 3600
        )
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
