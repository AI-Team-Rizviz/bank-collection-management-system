"""OIDC access-token validation (provider-agnostic).

Signature, issuer, audience and expiry are always verified; the accepted algorithms are a server-side
allow-list (asymmetric only), never taken from the token header. Keys come from the provider's JWKS,
discovered from `<issuer>/.well-known/openid-configuration` unless OIDC_JWKS_URL is set.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWKSet

log = logging.getLogger("iam.oidc")


class InvalidToken(Exception):
    """Any token problem. The reason is logged, never returned to the caller."""


class KeyResolver(Protocol):
    def signing_key(self, token: str) -> Any: ...


class StaticKeyResolver:
    """Keys from a fixed JWKS document (tests / air-gapped setups)."""

    def __init__(self, jwks: dict):
        self._set = PyJWKSet.from_dict(jwks)

    def signing_key(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid")
        for k in self._set.keys:
            if k.key_id == kid:
                return k.key
        raise InvalidToken("unknown key id")


class JwksKeyResolver:
    _MIN_REFRESH_SECONDS = 30  # throttle forced refreshes (unknown `kid` must not become a fetch amplifier)

    def __init__(self, issuer: str, jwks_url: str | None, ttl_seconds: int, client: httpx.Client | None = None):
        self._issuer = issuer.rstrip("/")
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._client = client or httpx.Client(timeout=5.0, follow_redirects=False)
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._loaded_at = 0.0

    def _discover(self) -> str:
        r = self._client.get(f"{self._issuer}/.well-known/openid-configuration")
        r.raise_for_status()
        doc = r.json()
        if str(doc.get("issuer", "")).rstrip("/") != self._issuer:
            raise InvalidToken("discovery issuer mismatch")
        return doc["jwks_uri"]

    def _refresh(self) -> None:
        url = self._jwks_url or self._discover()
        r = self._client.get(url)
        r.raise_for_status()
        self._keys = {k.key_id: k.key for k in PyJWKSet.from_dict(r.json()).keys if k.key_id}
        self._loaded_at = time.monotonic()

    def signing_key(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid")
        with self._lock:
            age = time.monotonic() - self._loaded_at
            try:
                if not self._keys or age > self._ttl or (kid not in self._keys and age > self._MIN_REFRESH_SECONDS):
                    self._refresh()
            except Exception as exc:  # network/parse errors: fail closed, keep serving cached keys if we have them
                log.warning("JWKS refresh failed: %s", type(exc).__name__)
                if not self._keys:
                    raise InvalidToken("jwks unavailable") from exc
            if kid not in self._keys:
                raise InvalidToken("unknown key id")
            return self._keys[kid]


class TokenVerifier:
    def __init__(self, resolver: KeyResolver, *, issuer: str, audience: str, algorithms: list[str], leeway: int = 30):
        self._resolver, self._issuer, self._audience = resolver, issuer, audience
        self._algorithms, self._leeway = algorithms, leeway

    def verify(self, token: str) -> dict[str, Any]:
        try:
            key = self._resolver.signing_key(token)
            return jwt.decode(
                token,
                key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "aud", "sub"], "verify_signature": True},
            )
        except InvalidToken:
            raise
        except Exception as exc:  # jwt.PyJWTError, malformed headers, key-type mismatches ...
            log.info("token rejected: %s", type(exc).__name__)
            raise InvalidToken(type(exc).__name__) from exc


def build_verifier(settings) -> TokenVerifier | None:
    if not (settings.oidc_issuer and settings.oidc_audience):
        return None
    resolver = JwksKeyResolver(settings.oidc_issuer, settings.oidc_jwks_url, settings.jwks_cache_ttl_seconds)
    return TokenVerifier(
        resolver,
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        algorithms=settings.oidc_algorithms,
        leeway=settings.oidc_leeway_seconds,
    )
