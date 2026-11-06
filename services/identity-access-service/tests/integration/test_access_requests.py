"""Maker-checker: requests, independent approval, transactional apply, idempotency."""
import threading

import pytest
from sqlalchemy import func, select

from app.domain.models import AuditLog, RolePermission, UserAccessScope, UserRole

pytestmark = pytest.mark.db
A = "/api/v1"
J = "Business justification for this change"


def code(r):
    return r.json()["error"]["code"]


def req_role(w, who, target, role_code, **kw):
    return w.client.post(f"{A}/access-requests", headers=w.h(who), json={
        "request_type": "ASSIGN_ROLE", "target_user_id": str(target.id), "role_id": str(w.role(role_code).id),
        "justification": J, **kw})


def active_roles(w, user):
    w.db.expire_all()
    return {r.role.code for r in w.db.scalars(select(UserRole).where(UserRole.user_id == user.id, UserRole.status == "ACTIVE")).unique()}


def test_full_flow_privileged_role(w, admin, admin2):
    target = w.user("cand1")
    r = req_role(w, admin, target, "POLICY_APPROVER")
    assert r.status_code == 201 and r.json()["status"] == "PENDING"
    rid = r.json()["id"]
    assert active_roles(w, target) == set()                      # nothing changes while pending
    done = w.client.post(f"{A}/access-requests/{rid}/approve", json={"comment": "ok"}, headers=w.h(admin2))
    assert done.status_code == 200 and done.json()["status"] == "APPLIED", done.text
    assert done.json()["approvals"][0]["approver_id"] == str(admin2.id)
    assert active_roles(w, target) == {"POLICY_APPROVER"}
    w.db.expire_all()
    ur = w.db.scalars(select(UserRole).where(UserRole.user_id == target.id)).unique().one()
    assert str(ur.source_request_id) == rid and ur.assigned_by == admin2.id


def test_requester_cannot_approve_own_request(w, admin):
    target = w.user("cand2")
    rid = req_role(w, admin, target, "POLICY_APPROVER").json()["id"]
    r = w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin))
    assert r.status_code == 403 and code(r) == "separation_of_duties"
    assert active_roles(w, target) == set()
    assert w.client.get(f"{A}/access-requests/{rid}", headers=w.h(admin)).json()["status"] == "PENDING"


def test_beneficiary_cannot_approve_request_for_self(w, admin, admin2):
    rid = req_role(w, admin, admin2, "COMPLIANCE_AUDITOR")
    # admin2 is a SYSTEM_ADMINISTRATOR, which conflicts with auditor -> request itself is refused
    assert rid.status_code == 409 and code(rid) == "role_conflict"
    # use a non-conflicting privileged role: POLICY_ADMINISTRATOR also conflicts, so use a third admin as beneficiary
    third = w.user("sysadmin3", roles=["SYSTEM_ADMINISTRATOR"])
    scope = w.scope("GLOBAL")
    rid = w.client.post(f"{A}/access-requests", headers=w.h(admin), json={
        "request_type": "GRANT_SCOPE", "target_user_id": str(third.id), "scope_id": str(scope.id), "justification": J}).json()["id"]
    r = w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(third))
    assert r.status_code == 403 and code(r) == "separation_of_duties"


def test_unauthorized_approver_rejected(w, admin):
    sup = w.user("sup2", roles=["COLLECTION_SUPERVISOR"])
    target = w.user("cand3")
    rid = req_role(w, sup, target, "POLICY_APPROVER").json()["id"]     # supervisors may *request*
    other_sup = w.user("sup3", roles=["COLLECTION_SUPERVISOR"])
    assert w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(other_sup)).status_code == 403
    assert w.client.post(f"{A}/access-requests/{rid}/reject", headers=w.h(other_sup)).status_code == 403
    assert active_roles(w, target) == set()


def test_agent_cannot_even_request(w):
    agent = w.user("agent3", roles=["COLLECTION_AGENT"])
    assert req_role(w, agent, agent, "POLICY_APPROVER").status_code == 403


def test_rejected_request_changes_nothing(w, admin, admin2):
    target = w.user("cand4")
    rid = req_role(w, admin, target, "POLICY_APPROVER").json()["id"]
    r = w.client.post(f"{A}/access-requests/{rid}/reject", json={"comment": "no"}, headers=w.h(admin2))
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert active_roles(w, target) == set()
    # a decided request can neither be approved nor re-rejected
    assert w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2)).status_code == 409
    assert w.client.post(f"{A}/access-requests/{rid}/reject", headers=w.h(admin2)).status_code == 409
    assert active_roles(w, target) == set()


def test_duplicate_approval_applies_once(w, admin, admin2):
    target = w.user("cand5")
    rid = req_role(w, admin, target, "POLICY_APPROVER").json()["id"]
    first = w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2))
    second = w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2))
    assert first.status_code == 200 and second.status_code == 409 and code(second) == "request_not_pending"
    w.db.expire_all()
    assert w.db.scalar(select(func.count()).select_from(UserRole).where(UserRole.user_id == target.id)) == 1


def test_concurrent_approvals_apply_once(w, admin, admin2):
    admin3 = w.user("sysadmin3", roles=["SYSTEM_ADMINISTRATOR"])
    target = w.user("cand6")
    rid = req_role(w, admin, target, "POLICY_APPROVER").json()["id"]
    codes = []

    def go(approver):
        codes.append(w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(approver)).status_code)

    ts = [threading.Thread(target=go, args=(a,)) for a in (admin2, admin3, admin2, admin3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200, 409, 409, 409]
    w.db.expire_all()
    assert w.db.scalar(select(func.count()).select_from(UserRole).where(UserRole.user_id == target.id)) == 1


def test_duplicate_pending_request_rejected(w, admin):
    target = w.user("cand7")
    assert req_role(w, admin, target, "POLICY_APPROVER").status_code == 201
    r = req_role(w, admin, target, "POLICY_APPROVER")
    assert r.status_code == 409


def test_request_validation_at_creation(w, admin):
    target = w.user("cand8", roles=["POLICY_APPROVER"])
    assert req_role(w, admin, target, "POLICY_APPROVER").status_code == 409          # already held
    pa = w.user("cand9", roles=["POLICY_ADMINISTRATOR"])
    r = req_role(w, admin, pa, "POLICY_APPROVER")
    assert r.status_code == 409 and code(r) == "role_conflict"                        # maker may not become checker
    gone = w.user("cand10", status="INACTIVE")
    assert req_role(w, admin, gone, "POLICY_APPROVER").status_code == 409
    z = "00000000-0000-0000-0000-000000000000"
    assert w.client.post(f"{A}/access-requests", headers=w.h(admin), json={
        "request_type": "ASSIGN_ROLE", "target_user_id": z, "role_id": str(w.role("POLICY_APPROVER").id), "justification": J}
    ).status_code == 404


def test_self_privilege_escalation_blocked(w, admin, admin2):
    # 1) direct assignment to self
    assert w.client.post(f"{A}/users/{admin.id}/roles", json={"role_id": str(w.role("COLLECTION_AGENT").id)},
                         headers=w.h(admin)).status_code == 403
    # 2) request for self cannot be approved by self
    scope = w.scope("GLOBAL")
    rid = w.client.post(f"{A}/access-requests", headers=w.h(admin), json={
        "request_type": "GRANT_SCOPE", "target_user_id": str(admin.id), "scope_id": str(scope.id), "justification": J}).json()["id"]
    assert w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin)).status_code == 403
    w.db.expire_all()
    assert w.db.scalar(select(func.count()).select_from(UserAccessScope).where(UserAccessScope.user_id == admin.id)) == 0


def test_scope_request_flow(w, admin, admin2):
    sup = w.user("sup4", roles=["COLLECTION_SUPERVISOR"])
    scope = w.scope("PORTFOLIO", "PF-CARDS")
    rid = w.client.post(f"{A}/access-requests", headers=w.h(sup), json={
        "request_type": "GRANT_SCOPE", "target_user_id": str(sup.id), "scope_id": str(scope.id), "justification": J}).json()["id"]
    r = w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin))
    assert r.status_code == 200 and r.json()["status"] == "APPLIED"
    assert [s["scope"]["scope_value"] for s in w.client.get(f"{A}/users/{sup.id}/scopes", headers=w.h(admin)).json()] == ["PF-CARDS"]


def test_role_permission_request_flow(w, admin, admin2):
    h = w.h(admin)
    cust = w.client.post(f"{A}/roles", json={"code": "SPECIAL_ROLE", "name": "s"}, headers=h).json()["id"]
    perm = w.perm("policy.approve")
    body = {"request_type": "GRANT_ROLE_PERMISSION", "role_id": cust, "permission_id": str(perm.id), "justification": J}
    rid = w.client.post(f"{A}/access-requests", headers=h, json=body).json()["id"]
    assert w.client.get(f"{A}/roles/{cust}/permissions", headers=h).json() == []
    assert w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2)).json()["status"] == "APPLIED"
    assert [p["code"] for p in w.client.get(f"{A}/roles/{cust}/permissions", headers=h).json()] == ["policy.approve"]
    # and removing it from a *system* role also goes through approval
    agent_role = w.role("COLLECTION_AGENT")
    body = {"request_type": "REVOKE_ROLE_PERMISSION", "role_id": str(agent_role.id),
            "permission_id": str(w.perm("ptp.create").id), "justification": J}
    rid = w.client.post(f"{A}/access-requests", headers=h, json=body).json()["id"]
    assert w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2)).json()["status"] == "APPLIED"
    w.db.expire_all()
    assert w.db.get(RolePermission, (agent_role.id, w.perm("ptp.create").id)) is None


def test_changing_own_role_permissions_is_blocked(w, admin):
    h = w.h(admin)
    rid = w.client.post(f"{A}/roles", json={"code": "MY_ROLE", "name": "m"}, headers=h).json()["id"]
    # admin cannot hold an unrelated custom role, so give it directly then try to widen it
    w.db.add(UserRole(user_id=admin.id, role_id=__import__("uuid").UUID(rid)))
    w.db.commit()
    r = w.client.post(f"{A}/roles/{rid}/permissions", json={"permission_id": str(w.perm("report.view_team").id)}, headers=h)
    assert r.status_code == 403


def test_apply_failure_is_recorded_and_changes_nothing(w, admin, admin2):
    target = w.user("cand11")
    rid = req_role(w, admin, target, "POLICY_APPROVER").json()["id"]
    w.client.post(f"{A}/users/{target.id}/deactivate", headers=w.h(admin))      # state changes before approval
    r = w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2))
    assert r.status_code == 200 and r.json()["status"] == "FAILED" and r.json()["failure_reason"] == "conflict"
    assert active_roles(w, target) == set()
    assert w.client.post(f"{A}/access-requests/{rid}/approve", headers=w.h(admin2)).status_code == 409


def test_listing_and_visibility(w, admin, admin2):
    sup = w.user("sup5", roles=["COLLECTION_SUPERVISOR"])
    sup_b = w.user("sup6", roles=["COLLECTION_SUPERVISOR"])
    t1, t2 = w.user("cand12"), w.user("cand13")
    mine = req_role(w, sup, t1, "POLICY_APPROVER").json()["id"]
    theirs = req_role(w, sup_b, t2, "POLICY_APPROVER").json()["id"]
    assert [i["id"] for i in w.client.get(f"{A}/access-requests", headers=w.h(sup)).json()["items"]] == [mine]
    assert w.client.get(f"{A}/access-requests/{theirs}", headers=w.h(sup)).status_code == 403
    assert w.client.get(f"{A}/access-requests/{mine}", headers=w.h(sup)).status_code == 200
    assert w.client.get(f"{A}/access-requests?status=PENDING", headers=w.h(admin)).json()["total"] == 2
    assert w.client.get(f"{A}/access-requests?status=BOGUS", headers=w.h(admin)).status_code == 422
    agent = w.user("agent4", roles=["COLLECTION_AGENT"])
    assert w.client.get(f"{A}/access-requests", headers=w.h(agent)).status_code == 403


def test_decisions_are_audited(w, admin, admin2):
    t1, t2 = w.user("cand14"), w.user("cand15")
    ok = req_role(w, admin, t1, "POLICY_APPROVER").json()["id"]
    no = req_role(w, admin, t2, "POLICY_APPROVER").json()["id"]
    w.client.post(f"{A}/access-requests/{ok}/approve", headers=w.h(admin2))
    w.client.post(f"{A}/access-requests/{no}/reject", headers=w.h(admin2))
    w.client.post(f"{A}/access-requests/{no}/approve", headers=w.h(admin))                         # SoD denial
    w.db.expire_all()
    rows = {(a.action, a.outcome, a.actor_user_id) for a in w.db.scalars(select(AuditLog))}
    assert ("access_request.create", "SUCCESS", admin.id) in rows
    assert ("access_request.approve", "SUCCESS", admin2.id) in rows
    assert ("access_request.reject", "SUCCESS", admin2.id) in rows
    assert ("user_role.assign", "SUCCESS", admin2.id) in rows
    # the requester deciding their own request is on record even though that request was rolled back
    assert ("access_request.decide", "DENIED", admin.id) in rows
