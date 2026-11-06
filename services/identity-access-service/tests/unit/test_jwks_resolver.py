"""OIDC discovery + JWKS handling against a mocked identity provider (no network)."""
import httpx
import pytest

from app.infrastructure.identity_provider import InvalidToken, JwksKeyResolver, TokenVerifier
from tests.conftest import AUDIENCE, ISSUER


class FakeIdP:
    def __init__(self, jwks, issuer=ISSUER):
        self.jwks, self.issuer, self.calls, self.fail = jwks, issuer, [], False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if self.fail:
            return httpx.Response(500)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": self.issuer, "jwks_uri": f"{ISSUER}/jwks"})
        if request.url.path.endswith("/jwks"):
            return httpx.Response(200, json=self.jwks)
        return httpx.Response(404)


def resolver(idp, ttl=300, jwks_url=None):
    return JwksKeyResolver(ISSUER, jwks_url, ttl, client=httpx.Client(transport=httpx.MockTransport(idp)))


def verifier(r):
    return TokenVerifier(r, issuer=ISSUER, audience=AUDIENCE, algorithms=["RS256"], leeway=0)


def test_discovers_jwks_and_caches(jwks, mint):
    idp = FakeIdP(jwks)
    v = verifier(resolver(idp))
    assert v.verify(mint("a"))["sub"] == "a"
    assert v.verify(mint("b"))["sub"] == "b"
    assert len([c for c in idp.calls if c.endswith("openid-configuration")]) == 1 and len(idp.calls) == 2  # cached


def test_explicit_jwks_url_skips_discovery(jwks, mint):
    idp = FakeIdP(jwks)
    verifier(resolver(idp, jwks_url=f"{ISSUER}/jwks")).verify(mint("a"))
    assert not any("well-known" in c for c in idp.calls)


def test_discovery_with_wrong_issuer_is_rejected(jwks, mint):
    with pytest.raises(InvalidToken):
        verifier(resolver(FakeIdP(jwks, issuer="https://impostor.invalid"))).verify(mint("a"))


def test_unknown_kid_triggers_throttled_refresh(jwks, mint):
    idp = FakeIdP(jwks)
    r = resolver(idp)
    v = verifier(r)
    v.verify(mint("a"))
    n = len(idp.calls)
    for _ in range(5):
        with pytest.raises(InvalidToken):
            v.verify(mint("a", kid="rotated-away"))
    assert len(idp.calls) == n  # attackers cannot turn bogus kids into a fetch storm
    r._loaded_at -= 60           # after the throttle window a rotated key is picked up
    with pytest.raises(InvalidToken):
        v.verify(mint("a", kid="rotated-away"))
    assert len(idp.calls) > n


def test_idp_outage_keeps_serving_cached_keys_but_fails_closed_when_empty(jwks, mint):
    idp = FakeIdP(jwks)
    r = resolver(idp, ttl=10)
    v = verifier(r)
    v.verify(mint("a"))
    idp.fail, r._loaded_at = True, r._loaded_at - 3600       # expired cache + broken IdP
    assert v.verify(mint("a"))["sub"] == "a"
    cold = verifier(resolver(idp))
    with pytest.raises(InvalidToken):
        cold.verify(mint("a"))


def test_build_verifier_requires_issuer_and_audience():
    from app.core.config import Settings
    from app.infrastructure.identity_provider import build_verifier
    assert build_verifier(Settings(database_url="postgresql+psycopg://x@h/d", oidc_issuer=None, oidc_audience=None,
                                   _env_file=None)) is None
    s = Settings(database_url="postgresql+psycopg://x@h/d", oidc_issuer="https://idp.example.invalid", oidc_audience="a",
                 _env_file=None)
    assert build_verifier(s) is not None
