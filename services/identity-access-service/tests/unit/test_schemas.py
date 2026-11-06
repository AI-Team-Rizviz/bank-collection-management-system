import uuid

import pytest
from pydantic import ValidationError

from app.schemas.access_requests import AccessRequestCreate
from app.schemas.roles import RoleCreate
from app.schemas.scopes import ScopeCreate
from app.schemas.users import UserCreate

U, R, P, S = (str(uuid.uuid4()) for _ in range(4))
J = "Needed for coverage during leave"


@pytest.mark.parametrize("bad", [
    dict(username="Ab", display_name="x", email="a@example.invalid", external_identity_id="s"),
    dict(username="UPPER", display_name="x", email="a@example.invalid", external_identity_id="s"),
    dict(username="ok_user", display_name="x", email="not-an-email", external_identity_id="s"),
    dict(username="ok_user", display_name="  ", email="a@example.invalid", external_identity_id="s"),
    dict(username="ok_user", display_name="x", email="a@example.invalid", external_identity_id="s", is_admin=True),
])
def test_user_create_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        UserCreate(**bad)


def test_user_email_normalised():
    assert UserCreate(username="ok_user", display_name="x", email="A@Example.INVALID", external_identity_id="s").email == "a@example.invalid"


@pytest.mark.parametrize("bad", [
    dict(scope_type="TEAM"), dict(scope_type="GLOBAL", scope_value="X1"), dict(scope_type="GALAXY", scope_value="X1"),
    dict(scope_type="BRANCH", scope_value="lower case"), dict(scope_type="OWN", scope_value="BR-1"),
])
def test_invalid_scopes_rejected(bad):
    with pytest.raises(ValidationError):
        ScopeCreate(name="n", **bad)


def test_valid_scopes():
    ScopeCreate(scope_type="GLOBAL", name="g")
    ScopeCreate(scope_type="BRANCH", scope_value="BR-001", name="b")


def test_role_code_format():
    with pytest.raises(ValidationError):
        RoleCreate(code="lower", name="x")
    with pytest.raises(ValidationError):
        RoleCreate(code="OK_ROLE", name="x", is_system=True)


@pytest.mark.parametrize("payload", [
    dict(request_type="ASSIGN_ROLE", role_id=R),
    dict(request_type="ASSIGN_ROLE", target_user_id=U, role_id=R, scope_id=S),
    dict(request_type="GRANT_SCOPE", target_user_id=U),
    dict(request_type="GRANT_ROLE_PERMISSION", role_id=R),
    dict(request_type="GRANT_ROLE_PERMISSION", role_id=R, permission_id=P, target_user_id=U),
    dict(request_type="NOPE", role_id=R),
    dict(request_type="ASSIGN_ROLE", target_user_id=U, role_id=R, justification="short"),
])
def test_access_request_shape(payload):
    payload.setdefault("justification", J)
    with pytest.raises(ValidationError):
        AccessRequestCreate(**payload)


def test_access_request_ok():
    AccessRequestCreate(request_type="ASSIGN_ROLE", target_user_id=U, role_id=R, justification=J)
    AccessRequestCreate(request_type="REVOKE_ROLE_PERMISSION", role_id=R, permission_id=P, justification=J)
