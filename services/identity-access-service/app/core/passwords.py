"""Password hashing (scrypt from the standard library; no extra dependency).

Stored format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`` so parameters can be raised later without breaking old hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
MIN_LENGTH, MAX_LENGTH = 10, 128


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(_derive(password, salt, _N, _R, _P))}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. A missing/invalid hash still burns a derivation so timing does not reveal it."""
    try:
        algo, n, r, p, salt, digest = (stored or "").split("$")
        if algo != "scrypt":
            raise ValueError
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, expected)
    except Exception:
        _derive(password, b"\0" * 16, _N, _R, _P)
        return False


def check_strength(password: str) -> None:
    if not (MIN_LENGTH <= len(password) <= MAX_LENGTH):
        raise ValueError(f"Password must be {MIN_LENGTH}-{MAX_LENGTH} characters long")
