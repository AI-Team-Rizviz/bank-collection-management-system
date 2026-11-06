"""Username/password login."""
import pytest

from tests.conftest import PASSWORD

pytestmark = pytest.mark.db
LOGIN = "/api/v1/auth/login"


def login(client, username, password):
    return client.post(LOGIN, json={"username": username, "password": password})


def test_login_returns_working_token(w, admin):
    r = login(w.client, admin.username, PASSWORD)
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    me = w.client.get("/api/v1/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200


def test_username_is_case_insensitive(w, admin):
    assert login(w.client, admin.username.upper(), PASSWORD).status_code == 200


@pytest.mark.parametrize("username,password", [("sysadmin1", "wrong-password"), ("nobody", PASSWORD)])
def test_bad_credentials_are_indistinguishable(w, admin, username, password):
    r = login(w.client, username, password)
    assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid username or password"


def test_inactive_user_cannot_login(w):
    u = w.user("gone1", status="INACTIVE")
    assert login(w.client, u.username, PASSWORD).status_code == 401


def test_user_without_password_cannot_login(w):
    u = w.user("nopass1")
    u.password_hash = None
    w.db.commit()
    assert login(w.client, u.username, "").status_code == 422  # empty password rejected by validation
    assert login(w.client, u.username, PASSWORD).status_code == 401


def test_failed_login_is_audited(w, admin):
    login(w.client, admin.username, "wrong-password")
    r = w.client.get("/api/v1/audit-logs?action=auth.login_failed", headers=w.h(admin))
    assert r.status_code == 200 and r.json()["items"]


def test_admin_can_create_user_with_password(w, admin):
    body = {"username": "newagent1", "display_name": "New Agent", "email": "newagent1@example.invalid",
            "password": "initial-password-1"}
    assert w.client.post("/api/v1/users", json=body, headers=w.h(admin)).status_code == 201
    assert login(w.client, "newagent1", "initial-password-1").status_code == 200
