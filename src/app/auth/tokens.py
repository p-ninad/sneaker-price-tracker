"""Token generation and hashing helpers."""

from __future__ import annotations

import hashlib
import secrets


def generate_session_token() -> str:
    """Generate an opaque session token for cookie storage."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for safe persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
