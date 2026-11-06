"""Pure RBAC + scope evaluation (no database)."""
import uuid

import pytest

from app.domain import policies
from app.domain.policies import PermissionGrant, ScopeGrant, evaluate

UID = uuid.uuid4()
OTHER = uuid.uuid4()


def grants(*items):
    return {g.code: g for g in items}


READ_ASSIGNED = PermissionGrant("case.read_assigned", False, ("OWN",))
READ_TEAM = PermissionGrant("case.read_team", False, ("TEAM",))
READ_PORTFOLIO = PermissionGrant("case.read_portfolio", False, ("PORTFOLIO", "BRANCH", "REGION", "GLOBAL"))
POLICY_READ = PermissionGrant("policy.read", False, None)


def ev(perm, g, scopes, resource):
    return evaluate(user_id=UID, permission=perm, grants=g, scopes=scopes, resource=resource)


def test_default_deny_without_grant():
    d = ev("case.read_team", {}, [ScopeGrant("GLOBAL", None)], {"assigned_team_id": "TEAM-001"})
    assert not d.allowed and d.reason == "permission_not_granted"


def test_unscoped_permission_needs_no_resource():
    assert ev("policy.read", grants(POLICY_READ), [], None).allowed


def test_scoped_permission_without_resource_is_denied():
    d = ev("case.read_team", grants(READ_TEAM), [ScopeGrant("TEAM", "TEAM-001")], None)
    assert not d.allowed and d.reason == "resource_context_required"


def test_agent_reads_own_case_only():
    g, s = grants(READ_ASSIGNED), [ScopeGrant("OWN", None)]
    assert ev("case.read_assigned", g, s, {"assigned_user_id": str(UID)}).allowed
    d = ev("case.read_assigned", g, s, {"assigned_user_id": str(OTHER)})
    assert not d.allowed and d.reason == "scope_mismatch"


def test_permission_without_matching_scope_grant_is_denied():
    # holds the permission but was never given an OWN scope
    assert not ev("case.read_assigned", grants(READ_ASSIGNED), [], {"assigned_user_id": str(UID)}).allowed


def test_supervisor_team_scope():
    g, s = grants(READ_TEAM), [ScopeGrant("TEAM", "TEAM-001")]
    assert ev("case.read_team", g, s, {"assigned_team_id": "TEAM-001"}).allowed
    assert not ev("case.read_team", g, s, {"assigned_team_id": "TEAM-002"}).allowed


def test_scope_type_not_allowed_for_permission_is_ignored():
    # GLOBAL cannot satisfy a TEAM-only permission
    assert not ev("case.read_team", grants(READ_TEAM), [ScopeGrant("GLOBAL", None)], {"assigned_team_id": "T"}).allowed


@pytest.mark.parametrize("scope,resource,ok", [
    (("PORTFOLIO", "PF-CARDS"), {"portfolio_id": "PF-CARDS"}, True),
    (("PORTFOLIO", "PF-CARDS"), {"portfolio_id": "PF-SCOOTY"}, False),
    (("BRANCH", "BR-001"), {"branch_id": "BR-001"}, True),
    (("REGION", "REG-NORTH"), {"region_id": "REG-SOUTH"}, False),
    (("GLOBAL", None), {"portfolio_id": "anything"}, True),
])
def test_portfolio_scopes(scope, resource, ok):
    assert ev("case.read_portfolio", grants(READ_PORTFOLIO), [ScopeGrant(*scope)], resource).allowed is ok


def test_missing_resource_attribute_does_not_match():
    assert not ev("case.read_team", grants(READ_TEAM), [ScopeGrant("TEAM", "TEAM-001")], {"branch_id": "BR-001"}).allowed


def test_maker_checker_triggers():
    assert policies.scope_needs_approval("GLOBAL") and policies.scope_needs_approval("PORTFOLIO")
    assert policies.scope_needs_approval("REGION")
    assert not policies.scope_needs_approval("TEAM") and not policies.scope_needs_approval("OWN")
    assert policies.role_needs_approval(is_privileged=True) and not policies.role_needs_approval(is_privileged=False)
    assert policies.role_permission_change_needs_approval(role_is_system=True, permission_is_sensitive=False)
    assert policies.role_permission_change_needs_approval(role_is_system=False, permission_is_sensitive=True)
    assert not policies.role_permission_change_needs_approval(role_is_system=False, permission_is_sensitive=False)
