import pytest

pytestmark = pytest.mark.db
A = "/api/v1"


def code(r):
    return r.json()["error"]["code"]


def test_seed_loaded_all_ten_roles(w, admin):
    items = w.client.get(f"{A}/roles?limit=50", headers=w.h(admin)).json()["items"]
    assert len(items) == 10 and all(r["is_system"] for r in items)
    assert not any("INTEGRATION" in r["code"] or "SUPPORT" in r["code"] for r in items)


def test_create_custom_role(w, admin):
    r = w.client.post(f"{A}/roles", json={"code": "BRANCH_REVIEWER", "name": "Branch Reviewer"}, headers=w.h(admin))
    assert r.status_code == 201
    assert r.json()["is_system"] is False and r.json()["is_privileged"] is False
    assert w.client.get(f"{A}/roles/{r.json()['id']}", headers=w.h(admin)).json()["code"] == "BRANCH_REVIEWER"


def test_duplicate_role_code(w, admin):
    body = {"code": "BRANCH_REVIEWER", "name": "x"}
    w.client.post(f"{A}/roles", json=body, headers=w.h(admin))
    assert w.client.post(f"{A}/roles", json=body, headers=w.h(admin)).status_code == 409
    assert w.client.post(f"{A}/roles", json={"code": "COLLECTION_AGENT", "name": "x"}, headers=w.h(admin)).status_code == 409


def test_cannot_create_privileged_or_system_role_via_api(w, admin):
    for extra in ({"is_privileged": True}, {"is_system": True}):
        r = w.client.post(f"{A}/roles", json={"code": "SNEAKY_ROLE", "name": "x", **extra}, headers=w.h(admin))
        assert r.status_code == 422


def test_unauthorized_role_modification(w):
    sup = w.user("sup1", roles=["COLLECTION_SUPERVISOR"])
    agent = w.role("COLLECTION_AGENT")
    assert w.client.post(f"{A}/roles", json={"code": "X_ROLE", "name": "x"}, headers=w.h(sup)).status_code == 403
    assert w.client.patch(f"{A}/roles/{agent.id}", json={"description": "x"}, headers=w.h(sup)).status_code == 403
    assert w.client.get(f"{A}/roles", headers=w.h(sup)).status_code == 403


def test_system_role_protection(w, admin):
    h, role = w.h(admin), w.role("COLLECTION_AGENT")
    for patch in ({"name": "Renamed"}, {"status": "INACTIVE"}):
        r = w.client.patch(f"{A}/roles/{role.id}", json=patch, headers=h)
        assert r.status_code == 409 and code(r) == "system_role_protected"
    assert w.client.patch(f"{A}/roles/{role.id}", json={"description": "doc only"}, headers=h).status_code == 200


def test_custom_role_can_be_updated_and_deactivated(w, admin):
    h = w.h(admin)
    rid = w.client.post(f"{A}/roles", json={"code": "TEMP_ROLE", "name": "t"}, headers=h).json()["id"]
    r = w.client.patch(f"{A}/roles/{rid}", json={"name": "T2", "status": "INACTIVE"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "INACTIVE"


def test_permission_catalog_is_read_only(w, admin):
    h = w.h(admin)
    page = w.client.get(f"{A}/permissions?limit=200", headers=h).json()
    codes = {p["code"] for p in page["items"]}
    assert {"policy.approve", "iam.access.approve", "case.read_team", "ptp.create"} <= codes
    assert w.client.post(f"{A}/permissions", json={"code": "x.y"}, headers=h).status_code == 405
    assert w.client.get(f"{A}/permissions?category=policy", headers=h).json()["total"] == 10
    assert w.client.get(f"{A}/permissions?is_sensitive=true", headers=h).json()["total"] >= 5


def test_role_permissions_listing(w, admin):
    role = w.role("POLICY_APPROVER")
    codes = {p["code"] for p in w.client.get(f"{A}/roles/{role.id}/permissions", headers=w.h(admin)).json()}
    assert "policy.approve" in codes and "policy.create" not in codes  # approvers cannot author


def test_map_non_sensitive_permission_to_custom_role(w, admin):
    h = w.h(admin)
    rid = w.client.post(f"{A}/roles", json={"code": "REPORT_VIEWER", "name": "r"}, headers=h).json()["id"]
    pid = w.perm("report.view_team").id
    r = w.client.post(f"{A}/roles/{rid}/permissions", json={"permission_id": str(pid)}, headers=h)
    assert r.status_code == 201
    assert w.client.post(f"{A}/roles/{rid}/permissions", json={"permission_id": str(pid)}, headers=h).status_code == 409
    assert w.client.delete(f"{A}/roles/{rid}/permissions/{pid}", headers=h).status_code == 204
    assert w.client.delete(f"{A}/roles/{rid}/permissions/{pid}", headers=h).status_code == 404


def test_sensitive_permission_requires_approval(w, admin):
    h = w.h(admin)
    rid = w.client.post(f"{A}/roles", json={"code": "REPORT_VIEWER", "name": "r"}, headers=h).json()["id"]
    r = w.client.post(f"{A}/roles/{rid}/permissions", json={"permission_id": str(w.perm("policy.approve").id)}, headers=h)
    assert r.status_code == 409 and code(r) == "approval_required"


def test_system_role_permissions_require_approval(w, admin):
    h, agent = w.h(admin), w.role("COLLECTION_AGENT")
    r = w.client.post(f"{A}/roles/{agent.id}/permissions", json={"permission_id": str(w.perm("report.view_team").id)}, headers=h)
    assert r.status_code == 409 and code(r) == "approval_required"
    existing = w.perm("ptp.create").id
    r = w.client.delete(f"{A}/roles/{agent.id}/permissions/{existing}", headers=h)
    assert r.status_code == 409 and code(r) == "approval_required"


def test_unknown_permission_or_role_is_404(w, admin):
    z = "00000000-0000-0000-0000-000000000000"
    rid = w.role("COLLECTION_AGENT").id
    assert w.client.get(f"{A}/roles/{z}/permissions", headers=w.h(admin)).status_code == 404
    custom = w.client.post(f"{A}/roles", json={"code": "TMP_ROLE", "name": "t"}, headers=w.h(admin)).json()["id"]
    assert w.client.post(f"{A}/roles/{custom}/permissions", json={"permission_id": z}, headers=w.h(admin)).status_code == 404
    assert rid


# --------------------------------------------------------------------- user <-> role
def test_assign_and_revoke_role(w, admin):
    h, u = w.h(admin), w.user("worker1")
    role = w.role("COLLECTION_AGENT")
    r = w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(role.id)}, headers=h)
    assert r.status_code == 201 and r.json()["role"]["code"] == "COLLECTION_AGENT"
    assert [x["role"]["code"] for x in w.client.get(f"{A}/users/{u.id}/roles", headers=h).json()] == ["COLLECTION_AGENT"]
    assert w.client.delete(f"{A}/users/{u.id}/roles/{role.id}", headers=h).status_code == 204
    assert w.client.get(f"{A}/users/{u.id}/roles", headers=h).json() == []
    assert w.client.delete(f"{A}/users/{u.id}/roles/{role.id}", headers=h).status_code == 404
    # revoked assignments can be granted again (history is kept, uniqueness applies to ACTIVE rows)
    assert w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(role.id)}, headers=h).status_code == 201


def test_duplicate_assignment_rejected(w, admin):
    h, u, role = w.h(admin), w.user("worker2"), w.role("COLLECTION_AGENT")
    body = {"role_id": str(role.id)}
    assert w.client.post(f"{A}/users/{u.id}/roles", json=body, headers=h).status_code == 201
    assert w.client.post(f"{A}/users/{u.id}/roles", json=body, headers=h).status_code == 409


@pytest.mark.parametrize("privileged", ["SYSTEM_ADMINISTRATOR", "POLICY_APPROVER", "POLICY_ADMINISTRATOR", "COMPLIANCE_AUDITOR"])
def test_privileged_roles_cannot_be_assigned_directly(w, admin, privileged):
    u = w.user("worker3")
    r = w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(w.role(privileged).id)}, headers=w.h(admin))
    assert r.status_code == 409 and code(r) == "approval_required"
    assert w.client.get(f"{A}/users/{u.id}/roles", headers=w.h(admin)).json() == []


def test_separation_of_duties_conflict(w, admin):
    sysadmin = w.user("worker4", roles=["SYSTEM_ADMINISTRATOR"])
    r = w.client.post(f"{A}/users/{sysadmin.id}/roles", json={"role_id": str(w.role("COLLECTION_AGENT").id)}, headers=w.h(admin))
    assert r.status_code == 409 and code(r) == "role_conflict"


def test_assignment_validation(w, admin):
    h, u, role = w.h(admin), w.user("worker5"), w.role("COLLECTION_AGENT")
    past = "2020-01-01T00:00:00+00:00"
    assert w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(role.id), "valid_until": past}, headers=h).status_code == 400
    assert w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(role.id), "valid_until": "2099-01-01T00:00:00"},
                         headers=h).status_code == 422  # naive timestamp
    z = "00000000-0000-0000-0000-000000000000"
    assert w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": z}, headers=h).status_code == 404
    gone = w.user("worker6", status="INACTIVE")
    assert w.client.post(f"{A}/users/{gone.id}/roles", json={"role_id": str(role.id)}, headers=h).status_code == 409


def test_cannot_assign_inactive_role(w, admin):
    h, u = w.h(admin), w.user("worker7")
    rid = w.client.post(f"{A}/roles", json={"code": "OLD_ROLE", "name": "o"}, headers=h).json()["id"]
    w.client.patch(f"{A}/roles/{rid}", json={"status": "INACTIVE"}, headers=h)
    assert w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": rid}, headers=h).status_code == 409


def test_role_assignment_grants_permissions(w, admin):
    u = w.user("worker8")
    assert w.client.get(f"{A}/me/permissions", headers=w.h(u)).json()["permissions"] == []
    w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(w.role("COLLECTION_AGENT").id)}, headers=w.h(admin))
    perms = {p["code"] for p in w.client.get(f"{A}/me/permissions", headers=w.h(u)).json()["permissions"]}
    assert "ptp.create" in perms and "policy.approve" not in perms and not any(p.startswith("iam.") for p in perms)
