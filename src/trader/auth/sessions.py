from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime) -> bool:
    value = expires_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= datetime.now(UTC)
