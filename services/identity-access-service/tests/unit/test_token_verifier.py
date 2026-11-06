"""Token validation: signature, issuer, audience, expiry, algorithm confusion."""
import pytest

from app.infrastructure.tokens import InvalidToken


def test_issue_and_verify_roundtrip(tokens):
    assert tokens.verify(tokens.issue("alice"))["sub"] == "alice"


def test_valid_token(tokens, mint):
    assert tokens.verify(mint("alice"))["sub"] == "alice"


def test_expired_token(tokens, mint):
    with pytest.raises(InvalidToken):
        tokens.verify(mint("alice", exp_in=-10))


def test_wrong_signature(tokens, mint):
    with pytest.raises(InvalidToken):
        tokens.verify(mint("alice", key="another-secret-another-secret-123456"))


def test_wrong_issuer(tokens, mint):
    with pytest.raises(InvalidToken):
        tokens.verify(mint("alice", iss="https://evil.invalid"))


def test_wrong_audience(tokens, mint):
    with pytest.raises(InvalidToken):
        tokens.verify(mint("alice", aud="someone-else"))


@pytest.mark.parametrize("claim", ["exp", "iss", "aud", "sub"])
def test_required_claims(tokens, mint, claim):
    with pytest.raises(InvalidToken):
        tokens.verify(mint("alice", drop=(claim,)))


def test_other_hmac_algorithm_rejected(tokens, mint):
    with pytest.raises(InvalidToken):
        tokens.verify(mint("alice", alg="HS512"))


def test_alg_none_rejected(tokens):
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    tok = f"{b64({'alg': 'none'})}.{b64({'sub': 'x', 'iss': 'bank-cms-iam', 'aud': 'bank-cms-iam', 'exp': 9999999999})}."
    with pytest.raises(InvalidToken):
        tokens.verify(tok)


def test_garbage(tokens):
    with pytest.raises(InvalidToken):
        tokens.verify("not.a.jwt")


def test_production_requires_a_strong_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY")
    from pydantic import ValidationError

    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x@h/d", app_env="production", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x@h/d", app_env="production", jwt_secret_key="short", _env_file=None)
    Settings(database_url="postgresql+psycopg://x@h/d", app_env="production", jwt_secret_key="x" * 32, _env_file=None)
