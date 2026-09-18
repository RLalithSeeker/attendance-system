"""Teacher auth — zero-dependency.

- ``users`` rows + salted ``pbkdf2_hmac`` (hashlib) password hashes. Password
  bytes are pre-hashed to stay clear of any 72-byte bcrypt-style pitfall.
- Opaque bearer ``auth_tokens`` hashed with SHA-256 at rest (never the token
  itself). Token TTL 12h default; logout revokes.
- No MFA, no OTP, no email — out of scope now, documented as a future gate.

This is entirely separate from the repo's global API-key gate (main.py
``_inject_key``): where an API key is configured it still applies on top of
attendance sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Callable, Optional

from .database import AttendanceDB, iso_utc, utcnow, _uuid

PBKDF2_ITERATIONS = 210_000
TOKEN_TTL_HOURS = 12

_HEX = "0123456789abcdef"


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS, salt.hex(), digest.hex())


def password_verify(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def salt_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TeacherAuth:
    """Holds the attendance DB + a token->user resolver. Uses Callable so tests
    can inject a mock resolver without touching the DB."""

    def __init__(self, db: AttendanceDB, resolve: Optional[Callable[[str], Optional[dict]]] = None):
        self.db = db
        self._resolve = resolve or self._resolve_token_default

    def _resolve_token_default(self, raw: str) -> Optional[dict]:
        row = self.db.query_one(
            "SELECT u.*, t.id AS token_id, t.user_id AS session_user, t.expires_at AS token_expiry"
            " FROM auth_tokens t JOIN users u ON u.id = t.user_id"
            " WHERE t.token_hash = :h AND t.active = 1",
            {"h": token_hash(raw)},
        )
        if not row:
            return None
        if row.get("token_expiry", iso_utc(utcnow())) < iso_utc(utcnow()):
            self.db.execute(
                "UPDATE auth_tokens SET active = 0 WHERE id = :id",
                {"id": row.get("token_id")},
            )
            return None
        if not row.get("active"):
            return None
        return {
            "user_id": row["id"],
            "email": row["email"],
            "role": row["role"],
        }

    def _now_oclock(self, iso: bool = False) -> str:
        return iso_utc()

    def authenticate_password(self, email: str, password: str) -> Optional[dict]:
        row = self.db.query_one(
            "SELECT * FROM users WHERE email = :email AND active = 1",
            {"email": email.strip().lower()})
        if not row:
            return None
        if not password_verify(password, row["password_hash"]):
            return None
        token = salt_token()
        self.db.execute(
            "INSERT INTO auth_tokens (id, user_id, token_hash, created_at, expires_at, active)"
            " VALUES (:id, :uid, :h, :c, :e, 1)",
            {
                "id": _uuid(), "uid": row["id"], "h": token_hash(token),
                "c": iso_utc(), "e": iso_utc(utcnow() + timedelta(hours=TOKEN_TTL_HOURS)),
            },
        )
        return {"token": token, "expires_at": iso_utc(utcnow() + timedelta(hours=TOKEN_TTL_HOURS))}

    def validate_token(self, raw: str) -> Optional[dict]:
        return self._resolve(raw)

    def revoke_token(self, raw: str) -> None:
        self.db.execute(
            "UPDATE auth_tokens SET active = 0 WHERE token_hash = :h",
            {"h": token_hash(raw)})

    def require_role(self, user: Optional[dict], roles=("teacher", "admin")) -> dict:
        if not user:
            from .errors import UnauthorizedError
            raise UnauthorizedError("Provide a valid Bearer token.")
        if user.get("role") not in roles:
            from .errors import ForbiddenError
            raise ForbiddenError("Role not allowed.")
        return user