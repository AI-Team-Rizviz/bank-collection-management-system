import pytest

pytestmark = pytest.mark.db
A = "/api/v1"
TEAM = {"code": "TEAM-900", "name": "Test Team", "branch_id": "BR-900", "region_id": "REG-NORTH"}


def code(r):
    return r.json()["error"]["code"]


def test_team_crud(w, admin):
    h = w.h(admin)
    r = w.client.post(f"{A}/teams", json=TEAM, headers=h)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert w.client.post(f"{A}/teams", json=TEAM, headers=h).status_code == 409
    assert w.client.get(f"{A}/teams/{tid}", headers=h).json()["code"] == "TEAM-900"
    assert w.client.patch(f"{A}/teams/{tid}", json={"name": "Renamed"}, headers=h).json()["name"] == "Renamed"
    assert w.client.get(f"{A}/teams?q=team-9", headers=h).json()["total"] == 1
    assert w.client.post(f"{A}/teams", json={**TEAM, "code": "bad code"}, headers=h).status_code == 422


def test_team_creation_defines_team_scope(w, admin):
    w.client.post(f"{A}/teams", json=TEAM, headers=w.h(admin))
    assert w.scope("TEAM", "TEAM-900") is not None


def test_membership_lifecycle(w, admin):
    h, u = w.h(admin), w.user("member1")
    tid = w.client.post(f"{A}/teams", json=TEAM, headers=h).json()["id"]
    r = w.client.post(f"{A}/teams/{tid}/members", json={"user_id": str(u.id), "member_role": "LEAD"}, headers=h)
    assert r.status_code == 201 and r.json()["member_role"] == "LEAD"
    assert w.client.post(f"{A}/teams/{tid}/members", json={"user_id": str(u.id)}, headers=h).status_code == 409
    assert len(w.client.get(f"{A}/teams/{tid}/members", headers=h).json()) == 1
    assert w.client.delete(f"{A}/teams/{tid}/members/{u.id}", headers=h).status_code == 204
    assert w.client.delete(f"{A}/teams/{tid}/members/{u.id}", headers=h).status_code == 404
    assert w.client.post(f"{A}/teams/{tid}/members", json={"user_id": str(u.id)}, headers=h).status_code == 201  # may rejoin


def test_user_can_belong_to_several_teams(w, admin):
    h, u = w.h(admin), w.user("multi1")
    t1 = w.client.post(f"{A}/teams", json=TEAM, headers=h).json()["id"]
    t2 = w.client.post(f"{A}/teams", json={**TEAM, "code": "TEAM-901"}, headers=h).json()["id"]
    for t in (t1, t2):
        assert w.client.post(f"{A}/teams/{t}/members", json={"user_id": str(u.id)}, headers=h).status_code == 201


def test_inactive_user_or_team_cannot_join(w, admin):
    h = w.h(admin)
    tid = w.client.post(f"{A}/teams", json=TEAM, headers=h).json()["id"]
    gone = w.user("gone1", status="INACTIVE")
    assert w.client.post(f"{A}/teams/{tid}/members", json={"user_id": str(gone.id)}, headers=h).status_code == 409


def test_team_endpoints_need_permissions(w):
    agent = w.user("agent1", roles=["COLLECTION_AGENT"])
    sup = w.user("sup1", roles=["COLLECTION_SUPERVISOR"])
    assert w.client.post(f"{A}/teams", json=TEAM, headers=w.h(agent)).status_code == 403
    assert w.client.get(f"{A}/teams", headers=w.h(agent)).status_code == 403
    assert w.client.get(f"{A}/teams", headers=w.h(sup)).status_code == 200     # iam.team.read
    assert w.client.post(f"{A}/teams", json=TEAM, headers=w.h(sup)).status_code == 403  # but not manage


# --------------------------------------------------------------------- scopes
def test_grant_and_revoke_team_scope(w, admin):
    h, u = w.h(admin), w.user("scoped1")
    sc = w.scope("TEAM", "TEAM-001")
    r = w.client.post(f"{A}/users/{u.id}/scopes", json={"scope_id": str(sc.id)}, headers=h)
    assert r.status_code == 201 and r.json()["scope"]["scope_value"] == "TEAM-001"
    assert w.client.post(f"{A}/users/{u.id}/scopes", json={"scope_id": str(sc.id)}, headers=h).status_code == 409
    assert len(w.client.get(f"{A}/users/{u.id}/scopes", headers=h).json()) == 1
    assert w.client.delete(f"{A}/users/{u.id}/scopes/{sc.id}", headers=h).status_code == 204
    assert w.client.delete(f"{A}/users/{u.id}/scopes/{sc.id}", headers=h).status_code == 404


@pytest.mark.parametrize("stype,value", [("REGION", "REG-NORTH"), ("PORTFOLIO", "PF-CARDS"), ("GLOBAL", None)])
def test_widening_scopes_need_approval(w, admin, stype, value):
    u = w.user("scoped2")
    r = w.client.post(f"{A}/users/{u.id}/scopes", json={"scope_id": str(w.scope(stype, value).id)}, headers=w.h(admin))
    assert r.status_code == 409 and code(r) == "approval_required"
    assert w.client.get(f"{A}/users/{u.id}/scopes", headers=w.h(admin)).json() == []


def test_cannot_grant_scope_to_self(w, admin):
    r = w.client.post(f"{A}/users/{admin.id}/scopes", json={"scope_id": str(w.scope("TEAM", "TEAM-001").id)}, headers=w.h(admin))
    assert r.status_code == 403


def test_define_scope_validation(w, admin):
    h = w.h(admin)
    ok = w.client.post(f"{A}/scopes", json={"scope_type": "BRANCH", "scope_value": "BR-777", "name": "b"}, headers=h)
    assert ok.status_code == 201
    assert w.client.post(f"{A}/scopes", json={"scope_type": "BRANCH", "scope_value": "BR-777", "name": "b"}, headers=h).status_code == 409
    for bad in ({"scope_type": "GALAXY", "scope_value": "X1"}, {"scope_type": "TEAM"}, {"scope_type": "GLOBAL", "scope_value": "X1"},
                {"scope_type": "BRANCH", "scope_value": "lower"}):
        assert w.client.post(f"{A}/scopes", json={"name": "n", **bad}, headers=h).status_code == 422
    r = w.client.post(f"{A}/scopes", json={"scope_type": "TEAM", "scope_value": "NO-SUCH-TEAM", "name": "n"}, headers=h)
    assert r.status_code == 409 and code(r) == "unknown_team"


def test_invalid_scope_id_on_grant(w, admin):
    u = w.user("scoped3")
    z = "00000000-0000-0000-0000-000000000000"
    assert w.client.post(f"{A}/users/{u.id}/scopes", json={"scope_id": z}, headers=w.h(admin)).status_code == 404
    assert w.client.post(f"{A}/users/{u.id}/scopes", json={"scope_id": "garbage"}, headers=w.h(admin)).status_code == 422


def test_scope_endpoints_need_permissions(w):
    agent = w.user("agent2", roles=["COLLECTION_AGENT"])
    assert w.client.get(f"{A}/scopes", headers=w.h(agent)).status_code == 403
    assert w.client.get(f"{A}/users/{agent.id}/scopes", headers=w.h(agent)).status_code == 403
