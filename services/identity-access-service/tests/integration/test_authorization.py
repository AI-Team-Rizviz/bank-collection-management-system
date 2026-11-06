"""Scope-aware authorization via the service-to-service decision API, using trusted resource fixtures."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.domain.models import AccessScope, Role, UserAccessScope, UserRole

pytestmark = pytest.mark.db
A = "/api/v1"


def check(w, user, permission, resource=None, *, by=None):
    body = {"subject": user.external_identity_id, "permission": permission}
    if resource is not None:
        body["resource"] = resource
    return w.client.post(f"{A}/authorization/check", json=body, headers=by or w.service)


@pytest.fixture
def cast(w):
    """Agents in two teams, their supervisors, a manager, an admin: the CMS cast."""
    c = type("Cast", (), {})()
    c.agent1 = w.user("agent1", ["COLLECTION_AGENT"], [("OWN", None)])
    c.agent2 = w.user("agent2", ["COLLECTION_AGENT"], [("OWN", None)])
    c.sup1 = w.user("sup1", ["COLLECTION_SUPERVISOR"], [("TEAM", "TEAM-001")])
    c.sup2 = w.user("sup2", ["COLLECTION_SUPERVISOR"], [("TEAM", "TEAM-002")])
    c.mgr = w.user("mgr1", ["COLLECTION_MANAGER"], [("TEAM", "TEAM-001"), ("PORTFOLIO", "PF-CARDS")])
    c.admin = w.user("admin1", ["SYSTEM_ADMINISTRATOR"])
    return c


def test_agent_accesses_own_assigned_case(w, cast):
    r = check(w, cast.agent1, "case.read_assigned", {"case_id": "CASE-1", "assigned_user_id": str(cast.agent1.id)})
    assert r.status_code == 200 and r.json()["allowed"] is True
    assert r.json()["matched_scope"] == {"scope_type": "OWN", "scope_value": None}


def test_agent_cannot_access_unrelated_case(w, cast):
    r = check(w, cast.agent1, "case.read_assigned", {"case_id": "CASE-2", "assigned_user_id": str(cast.agent2.id)})
    assert r.json()["allowed"] is False and r.json()["reason"] == "scope_mismatch"


def test_agent_has_no_team_or_portfolio_reach(w, cast):
    res = {"assigned_team_id": "TEAM-001", "portfolio_id": "PF-CARDS", "assigned_user_id": str(cast.agent1.id)}
    assert check(w, cast.agent1, "case.read_team", res).json()["reason"] == "permission_not_granted"
    assert check(w, cast.agent1, "case.read_portfolio", res).json()["allowed"] is False


def test_supervisor_reads_own_team_only(w, cast):
    assert check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["allowed"] is True
    r = check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-002"})
    assert r.json()["allowed"] is False and r.json()["reason"] == "scope_mismatch"
    assert check(w, cast.sup2, "case.read_team", {"assigned_team_id": "TEAM-002"}).json()["allowed"] is True


def test_manager_reads_authorised_portfolios_only(w, cast):
    assert check(w, cast.mgr, "case.read_portfolio", {"portfolio_id": "PF-CARDS"}).json()["allowed"] is True
    assert check(w, cast.mgr, "case.read_portfolio", {"portfolio_id": "PF-SCOOTY"}).json()["allowed"] is False
    assert check(w, cast.mgr, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["allowed"] is True
    assert check(w, cast.mgr, "case.read_team", {"assigned_team_id": "TEAM-003"}).json()["allowed"] is False


@pytest.mark.parametrize("perm,res", [
    ("case.read_assigned", {"assigned_user_id": "x"}), ("case.read_team", {"assigned_team_id": "TEAM-001"}),
    ("case.read_portfolio", {"portfolio_id": "PF-CARDS"}), ("ptp.read", {"assigned_user_id": "x"}),
    ("report.view_portfolio", {"portfolio_id": "PF-CARDS"}), ("recovery.read", {"portfolio_id": "PF-CARDS"}),
])
def test_system_admin_has_no_collection_data_access(w, cast, perm, res):
    r = check(w, cast.admin, perm, res)
    assert r.json()["allowed"] is False and r.json()["reason"] == "permission_not_granted"
    # even a GLOBAL scope would not help: roles and scopes are both required
    w.db.add(UserAccessScope(user_id=cast.admin.id, scope_id=w.scope("GLOBAL").id))
    w.db.commit()
    assert check(w, cast.admin, perm, res).json()["allowed"] is False


def test_scoped_permission_requires_resource_context(w, cast):
    r = check(w, cast.sup1, "case.read_team")
    assert r.json()["allowed"] is False and r.json()["reason"] == "resource_context_required"


def test_scope_without_matching_permission_grants_nothing(w):
    u = w.user("lonely1", roles=[], scopes=[("GLOBAL", None)])
    assert check(w, u, "case.read_portfolio", {"portfolio_id": "PF-CARDS"}).json()["allowed"] is False


def test_unknown_permission_denied(w, cast):
    assert check(w, cast.agent1, "made.up_permission").json()["allowed"] is False


def test_unknown_and_inactive_users_are_indistinguishable(w):
    gone = w.user("gone1", ["COLLECTION_AGENT"], status="INACTIVE")
    ghost = {"subject": "nobody-at-all", "permission": "case.read_assigned", "resource": {"assigned_user_id": "x"}}
    a = check(w, gone, "case.read_assigned", {"assigned_user_id": str(gone.id)}).json()
    b = w.client.post(f"{A}/authorization/check", json=ghost, headers=w.service).json()
    assert a["allowed"] is b["allowed"] is False and a["reason"] == b["reason"] == "user_not_authorized"


def test_sensitive_decisions_are_never_cacheable(w, admin, cast):
    sens = check(w, admin, "iam.access.approve").json()
    assert sens["allowed"] and sens["cache_ttl_seconds"] == 0
    plain = check(w, cast.agent1, "case.read_assigned", {"assigned_user_id": str(cast.agent1.id)}).json()
    assert plain["cache_ttl_seconds"] == 60
    assert check(w, cast.agent1, "case.read_assigned", {"assigned_user_id": "other"}).json()["cache_ttl_seconds"] == 0


def test_revocation_takes_effect_immediately_and_bumps_version(w, admin, cast):
    res = {"assigned_user_id": str(cast.agent1.id)}
    before = check(w, cast.agent1, "case.read_assigned", res).json()
    assert before["allowed"]
    role = w.role("COLLECTION_AGENT")
    assert w.client.delete(f"{A}/users/{cast.agent1.id}/roles/{role.id}", headers=w.h(admin)).status_code == 204
    after = check(w, cast.agent1, "case.read_assigned", res).json()
    assert after["allowed"] is False and after["authz_version"] > before["authz_version"]


def test_revoked_scope_and_deactivation_take_effect_immediately(w, admin, cast):
    sc = w.scope("TEAM", "TEAM-001")
    assert w.client.delete(f"{A}/users/{cast.sup1.id}/scopes/{sc.id}", headers=w.h(admin)).status_code == 204
    assert check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["allowed"] is False
    w.client.post(f"{A}/users/{cast.agent2.id}/deactivate", headers=w.h(admin))
    assert check(w, cast.agent2, "case.read_assigned", {"assigned_user_id": str(cast.agent2.id)}).json()["allowed"] is False


def test_expired_role_and_scope_do_not_grant(w, cast):
    past = datetime.now(UTC) - timedelta(hours=1)
    long_ago = datetime.now(UTC) - timedelta(days=2)
    # valid_from must precede valid_until (CHECK), so move both
    w.db.execute(update(UserRole).where(UserRole.user_id == cast.sup1.id).values(valid_from=long_ago, valid_until=past))
    w.db.commit()
    assert check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["allowed"] is False
    w.db.execute(update(UserRole).where(UserRole.user_id == cast.sup1.id).values(valid_until=None))
    w.db.execute(update(UserAccessScope).where(UserAccessScope.user_id == cast.sup1.id).values(valid_from=long_ago, valid_until=past))
    w.db.commit()
    assert check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["allowed"] is False


def test_inactive_role_or_scope_definition_does_not_grant(w, cast):
    w.db.execute(update(Role).where(Role.code == "COLLECTION_SUPERVISOR").values(status="INACTIVE"))
    w.db.commit()
    assert check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["reason"] == "permission_not_granted"
    w.db.execute(update(Role).where(Role.code == "COLLECTION_SUPERVISOR").values(status="ACTIVE"))
    w.db.execute(update(AccessScope).where(AccessScope.scope_value == "TEAM-001").values(status="INACTIVE"))
    w.db.commit()
    assert check(w, cast.sup1, "case.read_team", {"assigned_team_id": "TEAM-001"}).json()["allowed"] is False


def test_check_by_user_id(w, cast):
    r = w.client.post(f"{A}/authorization/check", headers=w.service, json={
        "user_id": str(cast.sup1.id), "permission": "case.read_team", "resource": {"assigned_team_id": "TEAM-001"}})
    assert r.json()["allowed"] is True and r.json()["user_id"] == str(cast.sup1.id)


# --------------------------------------------------------------- who may call /authorization/check
def test_end_user_cannot_supply_resource_attributes(w, cast):
    r = w.client.post(f"{A}/authorization/check", headers=w.h(cast.agent1), json={
        "permission": "case.read_assigned", "resource": {"assigned_user_id": str(cast.agent1.id)}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "service_identity_required"


def test_end_user_can_check_only_themselves(w, cast):
    ok = w.client.post(f"{A}/authorization/check", headers=w.h(cast.admin), json={"permission": "iam.user.read"})
    assert ok.status_code == 200 and ok.json()["allowed"] is True
    other = w.client.post(f"{A}/authorization/check", headers=w.h(cast.agent1),
                          json={"subject": cast.admin.external_identity_id, "permission": "iam.user.read"})
    assert other.status_code == 403


def test_service_must_name_a_user(w):
    r = w.client.post(f"{A}/authorization/check", headers=w.service, json={"permission": "policy.read"})
    assert r.status_code == 400


def test_service_identity_cannot_use_admin_apis(w):
    assert w.client.get(f"{A}/users", headers=w.service).status_code == 403
    assert w.client.get(f"{A}/me", headers=w.service).status_code == 403


# --------------------------------------------------------------- /me
def test_me_endpoints(w, cast):
    me = w.client.get(f"{A}/me", headers=w.h(cast.mgr)).json()
    assert me["username"] == "mgr1" and me["roles"] == ["COLLECTION_MANAGER"]
    assert {(s["scope_type"], s["scope_value"]) for s in me["scopes"]} == {("TEAM", "TEAM-001"), ("PORTFOLIO", "PF-CARDS")}
    perms = w.client.get(f"{A}/me/permissions", headers=w.h(cast.mgr)).json()
    byc = {p["code"]: p for p in perms["permissions"]}
    assert byc["case.read_portfolio"]["allowed_scope_types"] == ["PORTFOLIO", "BRANCH", "REGION", "GLOBAL"]
    assert "iam.user.create" not in byc and perms["cache_ttl_seconds"] == 60


def test_admin_permissions_are_iam_only(w, cast):
    perms = {p["code"] for p in w.client.get(f"{A}/me/permissions", headers=w.h(cast.admin)).json()["permissions"]}
    assert perms and all(p.startswith("iam.") for p in perms)
    assert w.db.scalar(select(Role.id).where(Role.code.like("%INTEGRATION%"))) is None
