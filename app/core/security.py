"""Security utilities: API key generation, hashing, and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_api_key(prefix: str = "rag_") -> tuple[str, str, str]:
    """Generate a cryptographically secure API key.

    Returns:
        tuple of (raw_key, key_hash, prefix)
        - raw_key: Returned once to the client; NEVER stored.
        - key_hash: SHA-256 digest persisted in the database.
        - prefix: Safe identifier for logging (first 8 characters).
    """
    token = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{token}"
    key_prefix = raw_key[:8]
    key_hash = hash_api_key(raw_key)
    return raw_key, key_hash, key_prefix


def hash_api_key(raw_key: str) -> str:
    """Compute the SHA-256 hexadecimal digest of an API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, expected_hash: str) -> bool:
    """Compare a raw API key against a stored SHA-256 hash in constant time."""
    computed_hash = hash_api_key(raw_key)
    return hmac.compare_digest(computed_hash, expected_hash)
