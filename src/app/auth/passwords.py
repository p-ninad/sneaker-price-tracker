"""Password hashing utilities."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

PASSWORD_ALGORITHM = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = 310_000
SALT_BYTES = 16


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> str:
    """Hash a plaintext password using PBKDF2-HMAC-SHA256."""
    if not password:
        raise ValueError("Password must not be empty")

    salt = secrets.token_bytes(SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return (
        f"{PASSWORD_ALGORITHM}${iterations}$"
        f"{_encode_bytes(salt)}${_encode_bytes(derived_key)}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    try:
        algorithm, iteration_value, encoded_salt, encoded_key = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False

        iterations = int(iteration_value)
        salt = _decode_bytes(encoded_salt)
        expected_key = _decode_bytes(encoded_key)
    except (AttributeError, ValueError, TypeError, binascii.Error):
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(derived_key, expected_key)


def needs_rehash(password_hash: str, *, target_iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> bool:
    """Return whether the password hash should be upgraded."""
    try:
        algorithm, iteration_value, *_ = password_hash.split("$", 3)
    except (AttributeError, ValueError):
        return True

    if algorithm != PASSWORD_ALGORITHM:
        return True

    try:
        iterations = int(iteration_value)
    except ValueError:
        return True

    return iterations < target_iterations
