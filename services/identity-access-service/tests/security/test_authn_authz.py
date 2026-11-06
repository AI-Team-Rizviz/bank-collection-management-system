"""Authentication enforcement, deny-by-default, error hygiene."""
import logging
import re
import uuid

import pytest

from tests.conftest import AUDIENCE, ISSUER

pytestmark = pytest.mark.db
A = "/api/v1"
Z = "00000000-0000-0000-0000-000000000001"


def operations(app):
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method in ("get", "post", "patch", "delete", "put"):
                yield method.upper(), path


def protected(app):
    return [(m, re.sub(r"\{[^}]+\}", Z, p)) for m, p in operations(app) if "/health/" not in p and p != "/api/v1/auth/login"]


def test_openapi_covers_the_agreed_surface(app):
    ops = {(m, re.sub(r"\{[^}]+\}", "{}", p)) for m, p in operations(app)}
    expected = {
        ("POST", "/api/v1/users"), ("GET", "/api/v1/users"), ("GET", "/api/v1/users/{}"), ("PATCH", "/api/v1/users/{}"),
        ("POST", "/api/v1/users/{}/deactivate"), ("POST", "/api/v1/users/{}/reactivate"),
        ("POST", "/api/v1/roles"), ("GET", "/api/v1/roles"), ("GET", "/api/v1/roles/{}"), ("PATCH", "/api/v1/roles/{}"),
        ("GET", "/api/v1/permissions"), ("GET", "/api/v1/roles/{}/permissions"), ("POST", "/api/v1/roles/{}/permissions"),
        ("DELETE", "/api/v1/roles/{}/permissions/{}"),
        ("GET", "/api/v1/users/{}/roles"), ("POST", "/api/v1/users/{}/roles"), ("DELETE", "/api/v1/users/{}/roles/{}"),
        ("POST", "/api/v1/teams"), ("GET", "/api/v1/teams"), ("GET", "/api/v1/teams/{}"), ("PATCH", "/api/v1/teams/{}"),
        ("POST", "/api/v1/teams/{}/members"), ("DELETE", "/api/v1/teams/{}/members/{}"),
        ("GET", "/api/v1/users/{}/scopes"), ("POST", "/api/v1/users/{}/scopes"), ("DELETE", "/api/v1/users/{}/scopes/{}"),
        ("GET", "/api/v1/me"), ("GET", "/api/v1/me/permissions"), ("POST", "/api/v1/authorization/check"),
        ("POST", "/api/v1/access-requests"), ("GET", "/api/v1/access-requests"), ("GET", "/api/v1/access-requests/{}"),
        ("POST", "/api/v1/access-requests/{}/approve"), ("POST", "/api/v1/access-requests/{}/reject"),
        ("GET", "/api/v1/audit-logs"), ("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health/live"), ("GET", "/api/v1/health/ready"),
    }
    assert expected <= ops, expected - ops


def test_every_protected_endpoint_requires_authentication(app, client):
    ops = protected(app)
    assert len(ops) > 30
    for method, path in ops:
        r = client.request(method, path, json={} if method in ("POST", "PATCH") else None)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers["www-authenticate"] == "Bearer"
        assert r.json()["error"]["code"] == "unauthenticated"


ENTITLEMENT_FREE = {("GET", f"{A}/me"), ("GET", f"{A}/me/permissions"), ("POST", f"{A}/authorization/check"),
                    ("GET", f"{A}/access-requests"), ("GET", f"{A}/access-requests/{Z}")}


def test_authenticated_user_without_roles_is_denied_everywhere(app, w):
    nobody = w.user("nobody1")
    for method, path in protected(app):
        if (method, path) in ENTITLEMENT_FREE:
            continue
        r = w.client.request(method, path, headers=w.h(nobody), json={} if method in ("POST", "PATCH") else None)
        assert r.status_code == 403, (method, path, r.status_code)


def test_entitlement_free_endpoints_still_deny_by_default(w):
    nobody = w.user("nobody2")
    assert w.client.get(f"{A}/access-requests", headers=w.h(nobody)).status_code == 403
    assert w.client.get(f"{A}/me/permissions", headers=w.h(nobody)).json()["permissions"] == []
    r = w.client.post(f"{A}/authorization/check", headers=w.h(nobody), json={"permission": "iam.user.read"})
    assert r.json()["allowed"] is False


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic abc", "bearer-only", "Token abc"])
def test_missing_or_malformed_authorization_header(w, header):
    h = {} if header is None else {"Authorization": header}
    r = w.client.get(f"{A}/me", headers=h)
    assert r.status_code == 401


def test_invalid_signature(w):
    r = w.client.get(f"{A}/me", headers=w.h("sub-x", key="another-secret-another-secret-123456"))
    assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid or expired token"


def test_expired_token(w, admin):
    assert w.client.get(f"{A}/me", headers=w.h(admin)).status_code == 200
    assert w.client.get(f"{A}/me", headers=w.h(admin, exp_in=-5)).status_code == 401


def test_wrong_issuer_and_audience(w, admin):
    assert w.client.get(f"{A}/me", headers=w.h(admin, iss="https://other.invalid")).status_code == 401
    assert w.client.get(f"{A}/me", headers=w.h(admin, aud="not-us")).status_code == 401
    assert (ISSUER, AUDIENCE) != ("https://other.invalid", "not-us")


def test_unsigned_and_other_algorithm_tokens(w, admin):
    assert w.client.get(f"{A}/me", headers=w.h(admin, alg="HS512")).status_code == 401
    assert w.client.get(f"{A}/me", headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.e30."}).status_code == 401


def test_error_bodies_do_not_reveal_the_reason(w, admin):
    reasons = {w.client.get(f"{A}/me", headers=h).text.split('"request_id"')[0] for h in (
        w.h(admin, exp_in=-5), w.h(admin, iss="https://x.invalid"), w.h(admin, aud="y"), {"Authorization": "Bearer junk"})}
    assert len(reasons) == 1


def test_valid_token_for_unknown_or_disabled_user_looks_identical(w):
    gone = w.user("disabled1", ["SYSTEM_ADMINISTRATOR"], status="INACTIVE")
    a = w.client.get(f"{A}/users", headers=w.h(gone))
    b = w.client.get(f"{A}/users", headers=w.h("subject-that-was-never-registered"))
    assert a.status_code == b.status_code == 403
    assert a.json()["error"]["code"] == b.json()["error"]["code"] and a.json()["error"]["message"] == b.json()["error"]["message"]


def test_disabled_user_cannot_perform_protected_actions(w, admin):
    victim = w.user("disabled2", ["SYSTEM_ADMINISTRATOR"])
    w.client.post(f"{A}/users/{victim.id}/deactivate", headers=w.h(admin))
    for method, path in [("GET", f"{A}/users"), ("GET", f"{A}/me"), ("POST", f"{A}/users"), ("GET", f"{A}/audit-logs")]:
        assert w.client.request(method, path, headers=w.h(victim), json={}).status_code == 403


def test_insufficient_permission_is_403_not_404(w):
    sup = w.user("sup1", ["COLLECTION_SUPERVISOR"])
    assert w.client.get(f"{A}/users/{uuid.uuid4()}", headers=w.h(sup)).status_code == 403   # no existence oracle


def test_error_envelope_shape(w, admin):
    r = w.client.get(f"{A}/users/{uuid.uuid4()}", headers=w.h(admin, ))
    body = r.json()["error"]
    assert set(body) == {"code", "message", "request_id"} and body["request_id"] == r.headers["x-request-id"]
    assert w.client.get(f"{A}/nope", headers=w.h(admin)).json()["error"]["code"] == "not_found"
    assert w.client.put(f"{A}/users", headers=w.h(admin)).status_code == 405


def test_request_id_is_propagated_only_when_safe(w, admin):
    ok = w.client.get(f"{A}/me", headers={**w.h(admin), "X-Request-ID": "trace-12345678"})
    assert ok.headers["x-request-id"] == "trace-12345678"
    bad = w.client.get(f"{A}/me", headers={**w.h(admin), "X-Request-ID": "x\r\ny: injected"})
    assert bad.headers["x-request-id"] != "x\r\ny: injected" and "injected" not in str(bad.headers)


def test_security_headers_and_no_default_cors(w, admin):
    r = w.client.get(f"{A}/me", headers={**w.h(admin), "Origin": "https://evil.invalid"})
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in r.headers


def test_cors_is_restricted_to_configured_origins(engine, tokens):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    s = Settings(database_url="postgresql+psycopg://x@h/d", app_env="test", cors_allowed_origins="https://cms.example.invalid",
                 _env_file=None)
    with TestClient(create_app(s, tokens)) as c:
        ok = c.options(f"{A}/me", headers={"Origin": "https://cms.example.invalid", "Access-Control-Request-Method": "GET"})
        no = c.options(f"{A}/me", headers={"Origin": "https://evil.invalid", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://cms.example.invalid"
    assert "access-control-allow-origin" not in no.headers


def test_tokens_never_appear_in_logs(w, admin, caplog):
    caplog.set_level(logging.DEBUG)
    bad = w.h("sub-x", key="another-secret-another-secret-123456")["Authorization"]
    good = w.h(admin)["Authorization"]
    w.client.get(f"{A}/me", headers={"Authorization": bad})
    w.client.get(f"{A}/me", headers={"Authorization": good})
    for tok in (bad, good):
        assert tok.split(" ")[1] not in caplog.text


def test_log_redaction_filter():
    from app.core.logging import RedactFilter
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "auth Bearer abc.def.ghi password=hunter2", None, None)
    RedactFilter().filter(rec)
    assert "abc.def.ghi" not in rec.msg and "hunter2" not in rec.msg


def test_authentication_unavailable_fails_closed(engine):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    s = Settings(database_url="postgresql+psycopg://x@h/d", app_env="test", _env_file=None, jwt_secret_key=None)
    with TestClient(create_app(s)) as c:
        r = c.get(f"{A}/me", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "authentication_unavailable"


# --------------------------------------------------------------- docs / health
def test_docs_available_in_development_and_disabled_in_production(engine, tokens):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    base = dict(database_url="postgresql+psycopg://x@h/d", _env_file=None)
    with TestClient(create_app(Settings(app_env="development", **base), tokens)) as dev:
        assert dev.get("/docs").status_code == 200
        schema = dev.get("/openapi.json").json()
        assert {t["name"] for t in schema["tags"]} >= {"Users", "Roles", "Permissions", "Teams", "Access Scopes",
                                                      "Authorization", "Access Requests", "Audit"}
        assert "bearerAuth" in str(schema["components"]["securitySchemes"]).replace("HTTPBearer", "bearerAuth")
    prod = Settings(app_env="production", jwt_secret_key="x" * 32, **base)
    with TestClient(create_app(prod, tokens)) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    forced = Settings(app_env="production", jwt_secret_key="x" * 32,
                      enable_api_docs="true", **base)
    with TestClient(create_app(forced, tokens)) as c:
        assert c.get("/docs").status_code == 200


def test_health_endpoints_are_public_and_minimal(client):
    assert client.get(f"{A}/health/live").json() == {"status": "ok"}
    r = client.get(f"{A}/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


def test_readiness_fails_closed_without_leaking_details(engine, tokens, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import database
    from app.main import create_app

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("password=secret host=db.internal")

        def commit(self): ...
        def rollback(self): ...
        def close(self): ...

    app = create_app(tokens=tokens)
    app.dependency_overrides[database.get_db] = lambda: iter([Boom()])
    with TestClient(app) as c:
        r = c.get(f"{A}/health/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


def test_unhandled_errors_are_generic(engine, tokens):
    from fastapi.testclient import TestClient

    from app.core import database
    from app.main import create_app

    def broken():
        raise RuntimeError("secret connection string postgresql://u:pw@h/d")
        yield  # pragma: no cover

    app = create_app(tokens=tokens)
    app.dependency_overrides[database.get_db] = broken
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get(f"{A}/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 500 and "postgresql" not in r.text and r.json()["error"]["code"] == "internal_error"


# --------------------------------------------------------------- privilege escalation
def test_admin_cannot_self_escalate_by_any_route(w, admin):
    h = w.h(admin)
    agent_role = w.role("COLLECTION_AGENT")
    assert w.client.post(f"{A}/users/{admin.id}/roles", json={"role_id": str(agent_role.id)}, headers=h).status_code == 403
    assert w.client.post(f"{A}/users/{admin.id}/scopes", json={"scope_id": str(w.scope("TEAM", "TEAM-001").id)}, headers=h).status_code == 403
    admin_role = w.role("SYSTEM_ADMINISTRATOR")
    r = w.client.post(f"{A}/roles/{admin_role.id}/permissions", json={"permission_id": str(w.perm("case.read_portfolio").id)}, headers=h)
    assert r.status_code == 403          # holds that role: cannot widen it for itself
    # cannot mint a privileged role, cannot invent permissions, cannot edit a system role's identity
    assert w.client.post(f"{A}/roles", json={"code": "ROOT_ROLE", "name": "x", "is_privileged": True}, headers=h).status_code == 422
    assert w.client.post(f"{A}/permissions", json={"code": "root.all"}, headers=h).status_code == 405
    assert w.client.patch(f"{A}/roles/{admin_role.id}", json={"status": "INACTIVE"}, headers=h).status_code == 409
    me = w.client.get(f"{A}/me/permissions", headers=h).json()["permissions"]
    assert not [p for p in me if not p["code"].startswith("iam.")]


def test_mass_assignment_is_rejected(w, admin):
    r = w.client.post(f"{A}/users", headers=w.h(admin), json={
        "external_identity_id": "m1", "username": "mass001", "display_name": "x", "email": "m@example.invalid",
        "status": "ACTIVE", "authz_version": 99, "roles": ["SYSTEM_ADMINISTRATOR"]})
    assert r.status_code == 422


def test_sql_injection_strings_are_inert(w, admin):
    h = w.h(admin)
    evil = "x'; DROP TABLE iam.users; --"
    assert w.client.get(f"{A}/users", params={"q": evil}, headers=h).status_code == 200
    assert w.client.get(f"{A}/audit-logs", params={"action": evil, "target_id": evil}, headers=h).status_code == 200
    assert w.client.post(f"{A}/users", json={"external_identity_id": evil, "username": "inject01", "display_name": evil,
                                             "email": "i@example.invalid"}, headers=h).status_code == 201
    assert w.client.get(f"{A}/users", headers=h).json()["total"] >= 2
