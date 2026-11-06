"""Session tokens issued by this service after a successful username/password login.

Signed HS256 JWTs with a server-side secret. The accepted algorithm is fixed here (never taken from the token header);
signature, issuer, audience and expiry are always verified.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import jwt

log = logging.getLogger("iam.tokens")
ALGORITHM = "HS256"
ISSUER = AUDIENCE = "bank-cms-iam"


class InvalidToken(Exception):
    """Any token problem. The reason is logged, never returned to the caller."""


class TokenService:
    def __init__(self, secret: str, ttl_seconds: int = 3600, leeway: int = 30):
        self._secret, self._ttl, self._leeway = secret, ttl_seconds, leeway

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def issue(self, subject: str) -> str:
        now = int(time.time())
        return jwt.encode({"sub": subject, "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + self._ttl},
                          self._secret, algorithm=ALGORITHM)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, self._secret, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER,
                              leeway=self._leeway, options={"require": ["exp", "iss", "aud", "sub"]})
        except Exception as exc:  # jwt.PyJWTError, malformed headers ...
            log.info("token rejected: %s", type(exc).__name__)
            raise InvalidToken(type(exc).__name__) from exc


def build_token_service(settings) -> TokenService | None:
    if not settings.jwt_secret_key:
        return None
    return TokenService(settings.jwt_secret_key, settings.access_token_ttl_seconds, settings.token_leeway_seconds)
