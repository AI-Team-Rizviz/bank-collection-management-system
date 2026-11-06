"""Token validation: signature, issuer, audience, expiry, algorithm confusion."""
import pytest

from app.infrastructure.identity_provider import InvalidToken
from tests.conftest import AUDIENCE, ISSUER


def test_valid_token(verifier, mint):
    assert verifier.verify(mint("alice"))["sub"] == "alice"


def test_expired_token(verifier, mint):
    with pytest.raises(InvalidToken):
        verifier.verify(mint("alice", exp_in=-10))


def test_wrong_signature(verifier, mint, other_key):
    with pytest.raises(InvalidToken):
        verifier.verify(mint("alice", key=other_key))


def test_wrong_issuer(verifier, mint):
    with pytest.raises(InvalidToken):
        verifier.verify(mint("alice", iss="https://evil.invalid"))
    assert ISSUER != "https://evil.invalid"


def test_wrong_audience(verifier, mint):
    with pytest.raises(InvalidToken):
        verifier.verify(mint("alice", aud="someone-else"))
    assert AUDIENCE != "someone-else"


@pytest.mark.parametrize("claim", ["exp", "iss", "aud", "sub"])
def test_required_claims(verifier, mint, claim):
    with pytest.raises(InvalidToken):
        verifier.verify(mint("alice", drop=(claim,)))


def test_unknown_key_id(verifier, mint):
    with pytest.raises(InvalidToken):
        verifier.verify(mint("alice", kid="not-in-jwks"))


def test_alg_none_rejected(verifier):
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    tok = f"{b64({'alg': 'none', 'kid': 'test-key-1'})}.{b64({'sub': 'x', 'iss': ISSUER, 'aud': AUDIENCE, 'exp': 9999999999})}."
    with pytest.raises(InvalidToken):
        verifier.verify(tok)


def test_hs256_with_public_key_confusion_rejected(verifier, jwks):
    """Classic algorithm-confusion forgery, built by hand because PyJWT refuses to encode it."""
    import base64
    import hashlib
    import hmac
    import json

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    head = b64(json.dumps({"alg": "HS256", "kid": "test-key-1"}).encode())
    body = b64(json.dumps({"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": 9999999999}).encode())
    sig = b64(hmac.new(json.dumps(jwks["keys"][0]).encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    with pytest.raises(InvalidToken):
        verifier.verify(f"{head}.{body}.{sig}")


def test_garbage(verifier):
    with pytest.raises(InvalidToken):
        verifier.verify("not.a.jwt")


def test_settings_reject_symmetric_algorithms():
    from pydantic import ValidationError

    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x@h/d", oidc_algorithms="HS256")


def test_production_requires_https_oidc(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER")
    monkeypatch.delenv("OIDC_AUDIENCE")
    from pydantic import ValidationError

    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x@h/d", app_env="production", oidc_issuer="http://idp", oidc_audience="a",
                 _env_file=None)
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x@h/d", app_env="production", _env_file=None)
