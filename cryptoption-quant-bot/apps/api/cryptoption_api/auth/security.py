"""Password hashing (Argon2) and signed session tokens (itsdangerous)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from itsdangerous.url_safe import URLSafeTimedSerializer

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    digest: str = _ph.hash(password)
    return digest


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bool(_ph.verify(password_hash, password))
    except VerifyMismatchError:
        return False
    except Exception:
        return False


class SessionTokens:
    """Signed, expiring session cookies. No server-side session store needed
    for single-user; the signature guarantees integrity."""

    def __init__(self, secret_key: str, ttl_minutes: int):
        self._serializer = URLSafeTimedSerializer(secret_key, salt="session")
        self._csrf_signer = TimestampSigner(secret_key, salt="csrf")
        self._ttl = ttl_minutes * 60

    def issue(self, user_id: int) -> str:
        token: str = self._serializer.dumps({"uid": user_id})
        return token

    def read(self, token: str) -> int | None:
        try:
            data = self._serializer.loads(token, max_age=self._ttl)
            return int(data["uid"])
        except (BadSignature, SignatureExpired, KeyError, ValueError):
            return None

    def issue_csrf(self) -> str:
        token: str = self._csrf_signer.sign(b"csrf").decode()
        return token

    def check_csrf(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            self._csrf_signer.unsign(token, max_age=self._ttl)
            return True
        except (BadSignature, SignatureExpired):
            return False
