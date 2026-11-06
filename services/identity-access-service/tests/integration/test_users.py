import pytest

pytestmark = pytest.mark.db
NEW = {"external_identity_id": "oidc-123", "username": "agent900", "display_name": "Agent Nine", "email": "agent900@example.invalid"}


def code(r):
    return r.json()["error"]["code"]


def test_create_get_list_update(w, admin):
    h = w.h(admin)
    r = w.client.post("/api/v1/users", json=NEW, headers=h)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["status"] == "ACTIVE" and "password" not in r.text
    assert w.client.get(f"/api/v1/users/{uid}", headers=h).json()["username"] == "agent900"
    page = w.client.get("/api/v1/users?q=agent9&limit=5", headers=h).json()
    assert page["total"] == 1 and page["limit"] == 5 and page["items"][0]["id"] == uid
    r = w.client.patch(f"/api/v1/users/{uid}", json={"display_name": "Renamed", "email": "NEW@example.invalid"}, headers=h)
    assert r.status_code == 200 and r.json()["display_name"] == "Renamed" and r.json()["email"] == "new@example.invalid"


def test_new_user_has_no_roles_or_access(w, admin):
    h = w.h(admin)
    uid = w.client.post("/api/v1/users", json=NEW, headers=h).json()["id"]
    assert w.client.get(f"/api/v1/users/{uid}/roles", headers=h).json() == []
    me = w.client.get("/api/v1/me/permissions", headers={"Authorization": w.h("oidc-123")["Authorization"]})
    assert me.status_code == 200 and me.json()["permissions"] == []


@pytest.mark.parametrize("field", ["external_identity_id", "username", "email"])
def test_duplicate_identity_rejected(w, admin, field):
    h = w.h(admin)
    assert w.client.post("/api/v1/users", json=NEW, headers=h).status_code == 201
    other = {"external_identity_id": "oidc-456", "username": "agent901", "display_name": "x", "email": "other@example.invalid"}
    other[field] = NEW[field]
    r = w.client.post("/api/v1/users", json=other, headers=h)
    assert r.status_code == 409 and code(r) == "conflict"


def test_duplicate_email_case_insensitive(w, admin):
    h = w.h(admin)
    w.client.post("/api/v1/users", json=NEW, headers=h)
    r = w.client.post("/api/v1/users", json={**NEW, "external_identity_id": "x", "username": "other01",
                                             "email": NEW["email"].upper()}, headers=h)
    assert r.status_code == 409


@pytest.mark.parametrize("patch", [{"username": "Bad Name"}, {"email": "nope"}, {"display_name": ""}, {"is_admin": True}, {}])
def test_invalid_input_rejected(w, admin, patch):
    h = w.h(admin)
    r = w.client.post("/api/v1/users", json={**NEW, **patch} if patch else {}, headers=h)
    assert r.status_code == 422 and code(r) == "validation_error"


def test_validation_errors_do_not_echo_input(w, admin):
    r = w.client.post("/api/v1/users", json={**NEW, "email": "super-secret-value"}, headers=w.h(admin))
    assert r.status_code == 422 and "super-secret-value" not in r.text


def test_patch_cannot_change_identity_fields(w, admin):
    uid = w.client.post("/api/v1/users", json=NEW, headers=w.h(admin)).json()["id"]
    r = w.client.patch(f"/api/v1/users/{uid}", json={"external_identity_id": "hijack"}, headers=w.h(admin))
    assert r.status_code == 422


def test_deactivate_reactivate(w, admin):
    target = w.user("victim1", roles=["COLLECTION_AGENT"])
    h = w.h(admin)
    v0 = target.authz_version
    r = w.client.post(f"/api/v1/users/{target.id}/deactivate", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "INACTIVE" and r.json()["authz_version"] > v0
    assert w.client.post(f"/api/v1/users/{target.id}/deactivate", headers=h).status_code == 409
    r = w.client.post(f"/api/v1/users/{target.id}/reactivate", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"


def test_cannot_deactivate_self(w, admin):
    r = w.client.post(f"/api/v1/users/{admin.id}/deactivate", headers=w.h(admin))
    assert r.status_code == 403


def test_deactivated_user_loses_access_immediately(w, admin):
    target = w.user("victim2", roles=["COLLECTION_AGENT"])
    assert w.client.get("/api/v1/me", headers=w.h(target)).status_code == 200
    w.client.post(f"/api/v1/users/{target.id}/deactivate", headers=w.h(admin))
    assert w.client.get("/api/v1/me", headers=w.h(target)).status_code == 403


def test_unauthorized_user_management(w):
    agent = w.user("agent1", roles=["COLLECTION_AGENT"])
    h = w.h(agent)
    assert w.client.post("/api/v1/users", json=NEW, headers=h).status_code == 403
    assert w.client.get("/api/v1/users", headers=h).status_code == 403
    assert w.client.post(f"/api/v1/users/{agent.id}/deactivate", headers=h).status_code == 403


def test_get_unknown_user_404(w, admin):
    r = w.client.get("/api/v1/users/00000000-0000-0000-0000-000000000000", headers=w.h(admin))
    assert r.status_code == 404 and code(r) == "not_found"


def test_malformed_uuid_is_422(w, admin):
    assert w.client.get("/api/v1/users/not-a-uuid", headers=w.h(admin)).status_code == 422


def test_pagination_bounds(w, admin):
    h = w.h(admin)
    assert w.client.get("/api/v1/users?limit=0", headers=h).status_code == 422
    assert w.client.get("/api/v1/users?limit=1000", headers=h).status_code == 422
    assert w.client.get("/api/v1/users?status=BOGUS", headers=h).status_code == 422


def test_like_wildcards_in_search_are_literal(w, admin):
    w.user("alice01")
    assert w.client.get("/api/v1/users?q=%25", headers=w.h(admin)).json()["total"] == 0


def test_reserved_service_subject_cannot_become_a_user(w, admin):
    r = w.client.post("/api/v1/users", json={**NEW, "external_identity_id": "svc-policy-service"}, headers=w.h(admin))
    assert r.status_code == 400
