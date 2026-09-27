"""Password hashing helpers.

Stdlib only (no new dependency) but deliberately memory/CPU hard:
scrypt with a per-password random salt. The previous scheme (HMAC-SHA256 keyed
by JWT_SECRET) is still accepted for verification so existing installs keep
working, and gets transparently upgraded on next successful login.
"""

import base64
import hashlib
import hmac
import os

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16

LEGACY_PREFIX = "hmac_sha256$"
SCRYPT_PREFIX = "scrypt$"


def _legacy_hash(password: str, secret: str) -> str:
    """The original (weak) derivation, kept only for verification/upgrade."""
    digest = hmac.new(secret.encode("utf-8"), password.strip().encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{LEGACY_PREFIX}{digest}"


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.scrypt(
        password.strip().encode("utf-8"),
        salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_N * SCRYPT_R * SCRYPT_P * 2,
    )
    return "{}{}${}${}${}${}".format(
        SCRYPT_PREFIX, SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def is_up_to_date(stored: str) -> bool:
    return bool(stored) and stored.startswith(SCRYPT_PREFIX)


def verify_password(plain_password: str, stored: str, legacy_secret: str = "") -> bool:
    """Verifies a password against a stored hash of either supported format.

    Returns False for malformed/unknown hashes rather than raising.
    """
    plain = (plain_password or "").strip()
    if not plain or not stored:
        return False

    if stored.startswith(SCRYPT_PREFIX):
        try:
            _, n, r, p, salt_b64, digest_b64 = stored.split("$")
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(digest_b64)
            candidate = hashlib.scrypt(
                plain.encode("utf-8"), salt=salt,
                n=int(n), r=int(r), p=int(p),
                dklen=len(expected),
                maxmem=int(n) * int(r) * int(p) * 2,
            )
        except Exception:
            return False
        return hmac.compare_digest(candidate, expected)

    if stored.startswith(LEGACY_PREFIX) and legacy_secret:
        return hmac.compare_digest(_legacy_hash(plain, legacy_secret), stored)

    return False


def looks_like_legacy(stored: str) -> bool:
    return bool(stored) and not stored.startswith(SCRYPT_PREFIX)


def needs_upgrade(stored: str) -> bool:
    """True when the stored hash predates scrypt and should be rewritten."""
    return looks_like_legacy(stored)
