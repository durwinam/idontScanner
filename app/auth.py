"""Password hashing helpers for idontScanner."""

from __future__ import annotations

import hashlib
import hmac
import secrets


SCRYPT_PARAMETERS = (16384, 8192, 4096)


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Create a salted scrypt password hash with a memory-aware fallback."""
    salt = salt or secrets.token_bytes(16)

    for n in SCRYPT_PARAMETERS:
        try:
            digest = hashlib.scrypt(
                password.encode(),
                salt=salt,
                n=n,
                r=8,
                p=1,
                dklen=64,
            )
            return f"scrypt${n}$8$1${salt.hex()}${digest.hex()}"
        except ValueError as exc:
            if "memory limit" not in str(exc).lower():
                raise

    raise RuntimeError("Unable to create password hash with available memory")


def verify_password(password: str, stored: str) -> bool:
    """Verify a stored scrypt password hash."""
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$", 5)
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=64,
        )
    except (TypeError, ValueError):
        try:
            salt_hex, digest_hex = stored.split(":", 1)
            digest = hashlib.scrypt(
                password.encode(),
                salt=bytes.fromhex(salt_hex),
                n=16384,
                r=8,
                p=1,
                dklen=64,
            )
        except (TypeError, ValueError):
            return False

    return hmac.compare_digest(digest.hex(), digest_hex)
