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
    """Verify supported idontScanner scrypt password formats.

    Supports the current six-field format and the installer format used by
    v3.5.0 (four fields: algorithm, N, salt, digest), plus the legacy
    ``salt:digest`` representation.
    """
    try:
        parts = stored.split("$")
        if len(parts) == 6 and parts[0] == "scrypt":
            _, n, r, p, salt_hex, digest_hex = parts
        elif len(parts) == 4 and parts[0] == "scrypt":
            _, n, salt_hex, digest_hex = parts
            r, p = "8", "1"
        else:
            raise ValueError("unsupported password hash format")

        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=64,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (TypeError, ValueError, OverflowError):
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
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (TypeError, ValueError, OverflowError):
            return False

