"""Test harness.

DB tests run against a DISPOSABLE PostgreSQL database that the suite creates and drops itself:
    export TEST_DATABASE_URL=postgresql+psycopg://<user>@127.0.0.1:<port>/postgres   # a role allowed to CREATE DATABASE
No production credentials are used or needed. Without TEST_DATABASE_URL the DB tests are skipped (loudly).
Reference data comes from the repo's seed package (data_seed/seed/identity) - the same code used in development.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data_seed"))  # reuse seed.identity

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
DB_NAME = f"iam_test_{uuid.uuid4().hex[:10]}"
ISSUER, AUDIENCE = "https://idp.test.invalid/realm", "bank-cms-iam"
SERVICE_SUB = "svc-policy-service"

from sqlalchemy.engine import make_url  # noqa: E402

if ADMIN_URL:
    TEST_URL = make_url(ADMIN_URL).set(database=DB_NAME).render_as_string(hide_password=False)
else:
    TEST_URL = "postgresql+psycopg://unused@127.0.0.1:1/unused"
os.environ.update({
    "APP_ENV": "test", "DATABASE_URL": TEST_URL, "DATABASE_SCHEMA": "iam", "OIDC_ISSUER": ISSUER,
    "OIDC_AUDIENCE": AUDIENCE, "SERVICE_SUBJECTS": SERVICE_SUB, "AUTHZ_CACHE_TTL_SECONDS": "60",
})

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.infrastructure.identity_provider import StaticKeyResolver, TokenVerifier  # noqa: E402


# ------------------------------------------------------------------ keys / tokens
def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def signing_key():
    return _new_key()


@pytest.fixture(scope="session")
def other_key():
    return _new_key()


@pytest.fixture(scope="session")
def jwks(signing_key):
    jwk = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": "test-key-1", "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture(scope="session")
def mint(signing_key):
    def _mint(sub: str, *, key=None, iss=ISSUER, aud=AUDIENCE, exp_in=300, kid="test-key-1", alg="RS256", extra=None,
              drop=()):
        now = int(time.time())
        claims = {"sub": sub, "iss": iss, "aud": aud, "iat": now, "exp": now + exp_in, **(extra or {})}
        for d in drop:
            claims.pop(d, None)
        return jwt.encode(claims, key or signing_key, algorithm=alg, headers={"kid": kid})

    return _mint


@pytest.fixture(scope="session")
def verifier(jwks):
    return TokenVerifier(StaticKeyResolver(jwks), issuer=ISSUER, audience=AUDIENCE, algorithms=["RS256"], leeway=0)


# ------------------------------------------------------------------ database
@pytest.fixture(scope="session")
def _database():
    if not ADMIN_URL:
        pytest.skip("TEST_DATABASE_URL not set: DB tests need a disposable PostgreSQL (see tests/conftest.py)")
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    cfg.attributes["url"] = TEST_URL
    command.upgrade(cfg, "head")
    yield TEST_URL
    from app.core.database import get_engine

    get_engine().dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
    admin.dispose()


ALL_TABLES = ("users", "roles", "permissions", "role_permissions", "role_conflicts", "user_roles", "team_members",
              "user_access_scopes", "access_requests", "access_approvals", "audit_logs", "teams", "access_scopes")


@pytest.fixture
def engine(_database):
    from app.core.database import get_engine

    eng = get_engine()
    from seed.identity import runner

    with eng.begin() as c:
        c.execute(text("TRUNCATE " + ", ".join(f"iam.{t}" for t in ALL_TABLES) + " RESTART IDENTITY CASCADE"))
    runner.seed_catalog(eng)  # fresh, identical reference data for every test
    return eng


@pytest.fixture
def db(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def app(engine, verifier):
    from app.main import create_app

    return create_app(verifier=verifier)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ------------------------------------------------------------------ world builder
class World:
    def __init__(self, db, client, mint):
        self.db, self.client, self.mint = db, client, mint

    # --- lookups
    def role(self, code):
        from sqlalchemy import select

        from app.domain.models import Role
        return self.db.scalar(select(Role).where(Role.code == code))

    def perm(self, code):
        from sqlalchemy import select

        from app.domain.models import Permission
        return self.db.scalar(select(Permission).where(Permission.code == code))

    def scope(self, stype, value=None):
        from sqlalchemy import select

        from app.domain.models import AccessScope
        return self.db.scalar(select(AccessScope).where(AccessScope.scope_type == stype, AccessScope.scope_value == value))

    def team(self, code):
        from sqlalchemy import select

        from app.domain.models import Team
        return self.db.scalar(select(Team).where(Team.code == code))

    # --- builders (direct DB setup; the API is what the tests exercise)
    def user(self, username, roles=(), scopes=(), status="ACTIVE"):
        from app.domain.models import User, UserAccessScope, UserRole
        u = User(external_identity_id=f"sub-{username}", username=username, display_name=username.title(),
                 email=f"{username}@example.invalid", status=status)
        self.db.add(u)
        self.db.flush()
        for r in roles:
            self.db.add(UserRole(user_id=u.id, role_id=self.role(r).id))
        for stype, value in scopes:
            self.db.add(UserAccessScope(user_id=u.id, scope_id=self.scope(stype, value).id))
        self.db.commit()
        return u

    def h(self, user, **kw):
        sub = user if isinstance(user, str) else user.external_identity_id
        return {"Authorization": f"Bearer {self.mint(sub, **kw)}"}

    @property
    def service(self):
        return {"Authorization": f"Bearer {self.mint(SERVICE_SUB)}"}

    def later(self, days=1):
        return (datetime.now(UTC) + timedelta(days=days)).isoformat()


@pytest.fixture
def w(db, client, mint):
    return World(db, client, mint)


@pytest.fixture
def admin(w):
    return w.user("sysadmin1", roles=["SYSTEM_ADMINISTRATOR"])


@pytest.fixture
def admin2(w):
    return w.user("sysadmin2", roles=["SYSTEM_ADMINISTRATOR"])
