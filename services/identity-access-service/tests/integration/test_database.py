"""Schema integrity, concurrency, audit, migrations and seeding."""
import threading
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import (
    AccessRequest,
    AccessScope,
    AuditLog,
    Base,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from tests.conftest import ADMIN_URL, TEST_URL

pytestmark = pytest.mark.db
A = "/api/v1"
SVC = Path(__file__).resolve().parents[2]


def mk_user(db, name):
    u = User(external_identity_id=f"s-{name}", username=name, display_name=name, email=f"{name}@example.invalid")
    db.add(u)
    db.flush()
    return u


# ----------------------------------------------------------------------------- integrity
def test_foreign_keys_enforced(db):
    db.add(UserRole(user_id=uuid.uuid4(), role_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        db.flush()


def test_cannot_delete_role_in_use(w, db):
    u = w.user("holder1", ["COLLECTION_AGENT"])
    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM iam.roles WHERE code = 'COLLECTION_AGENT'"))
        db.flush()
    assert u


@pytest.mark.parametrize("make", [
    lambda: User(external_identity_id="a", username="UPPER", display_name="x", email="a@example.invalid"),
    lambda: User(external_identity_id="a", username="valid1", display_name="x", email="UPPER@example.invalid"),
    lambda: User(external_identity_id="a", username="valid1", display_name="x", email="a@example.invalid", status="DELETED"),
    lambda: Role(code="lower", name="x"),
    lambda: Role(code="BAD_PRIV", name="x", is_privileged=True, is_system=False),
    lambda: AccessScope(scope_type="GLOBAL", scope_value="X1", name="x"),
    lambda: AccessScope(scope_type="TEAM", scope_value=None, name="x"),
    lambda: Permission(code="NoDots", description="x", category="c"),
    lambda: Permission(code="a.b", description="x", category="c", allowed_scope_types=["GALAXY"]),
])
def test_check_constraints(db, make):
    db.add(make())
    with pytest.raises(IntegrityError):
        db.flush()


def test_unique_constraints(db):
    mk_user(db, "dupe1")
    db.add(User(external_identity_id="s-dupe1", username="other1", display_name="x", email="o@example.invalid"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_access_request_shape_check(w, db):
    u = w.user("shape1")
    db.add(AccessRequest(request_type="ASSIGN_ROLE", requested_by=u.id, justification="long enough text"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_active_uniqueness_allows_history(w, db):
    u = w.user("hist1", ["COLLECTION_AGENT"])
    role = w.role("COLLECTION_AGENT")
    db.add(UserRole(user_id=u.id, role_id=role.id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.execute(text("UPDATE iam.user_roles SET status='REVOKED' WHERE user_id = :u"), {"u": u.id})
    db.add(UserRole(user_id=u.id, role_id=role.id))
    db.flush()  # a new ACTIVE row next to the REVOKED one is fine


def test_timestamps_are_timezone_aware(db):
    u = mk_user(db, "tz1")
    assert u.created_at.tzinfo is not None and u.updated_at.tzinfo is not None


# ----------------------------------------------------------------------------- transactions
def test_transaction_rollback_leaves_nothing(w, engine):
    with Session(engine) as s:
        u = mk_user(s, "rollback1")
        s.add(UserRole(user_id=u.id, role_id=w.role("COLLECTION_AGENT").id))
        s.flush()
        s.rollback()
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(User).where(User.username == "rollback1")) == 0


def test_savepoint_isolates_a_failed_insert(w, engine):
    with Session(engine) as s:
        u = mk_user(s, "sp1")
        role = w.role("COLLECTION_AGENT")
        s.add(UserRole(user_id=u.id, role_id=role.id))
        s.flush()
        with pytest.raises(IntegrityError), s.begin_nested():
            s.add(UserRole(user_id=u.id, role_id=role.id))
            s.flush()
        s.commit()
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(UserRole).where(UserRole.user_id == u.id)) == 1


def test_failed_request_rolls_back_whole_transaction(w, admin):
    """A 409 from the service must not leave half-applied state or a stray audit row for the failed action."""
    u = w.user("atomic1", ["COLLECTION_AGENT"])
    before = w.db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "user_role.assign"))
    r = w.client.post(f"{A}/users/{u.id}/roles", json={"role_id": str(w.role("COLLECTION_AGENT").id)}, headers=w.h(admin))
    assert r.status_code == 409
    w.db.expire_all()
    assert w.db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "user_role.assign")) == before


# ----------------------------------------------------------------------------- concurrency
def test_concurrent_role_assignment_is_safe(w, admin):
    u = w.user("race1")
    body = {"role_id": str(w.role("COLLECTION_AGENT").id)}
    codes = []

    def go():
        codes.append(w.client.post(f"{A}/users/{u.id}/roles", json=body, headers=w.h(admin)).status_code)

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [201] + [409] * 7
    w.db.expire_all()
    assert w.db.scalar(select(func.count()).select_from(UserRole).where(UserRole.user_id == u.id, UserRole.status == "ACTIVE")) == 1


def test_concurrent_user_creation_is_safe(w, admin):
    body = {"external_identity_id": "race-sub", "username": "racer01", "display_name": "x", "email": "racer01@example.invalid"}
    codes = []

    def go():
        codes.append(w.client.post(f"{A}/users", json=body, headers=w.h(admin)).status_code)

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [201] + [409] * 5


# ----------------------------------------------------------------------------- audit
def test_audit_log_is_append_only(w, admin):
    w.client.post(f"{A}/users/{admin.id}/deactivate", headers=w.h(admin))  # produces a denied audit row
    w.client.post(f"{A}/users", json={"external_identity_id": "a1", "username": "audit01", "display_name": "x",
                                      "email": "audit01@example.invalid"}, headers=w.h(admin))
    # even the table OWNER / superuser cannot rewrite history
    with create_engine(TEST_URL).begin() as c, pytest.raises(DBAPIError, match="append-only"):
        c.execute(text("UPDATE iam.audit_logs SET action = 'tampered'"))
    with create_engine(TEST_URL).begin() as c, pytest.raises(DBAPIError, match="append-only"):
        c.execute(text("DELETE FROM iam.audit_logs"))


def test_audit_records_actor_target_and_outcome(w, admin):
    h = w.h(admin, extra={"scope": "openid"})
    uid = w.client.post(f"{A}/users", json={"external_identity_id": "a2", "username": "audit02", "display_name": "x",
                                            "email": "audit02@example.invalid"}, headers=h).json()["id"]
    page = w.client.get(f"{A}/audit-logs?action=user.create&target_id={uid}", headers=h).json()
    row = page["items"][0]
    assert page["total"] == 1 and row["actor_user_id"] == str(admin.id) and row["outcome"] == "SUCCESS"
    assert row["request_id"] and row["actor_type"] == "USER" and row["target_type"] == "user"


def test_denied_attempts_are_audited_even_though_the_request_fails(w, admin):
    agent = w.user("agent9", ["COLLECTION_AGENT"])
    assert w.client.get(f"{A}/users", headers=w.h(agent)).status_code == 403
    rows = w.client.get(f"{A}/audit-logs?outcome=DENIED&actor_user_id={agent.id}", headers=w.h(admin)).json()["items"]
    assert [(r["action"], r["target_id"]) for r in rows] == [("authz.denied", "iam.user.read")]


def test_audit_endpoint_filters_pages_and_is_restricted(w, admin):
    h = w.h(admin)
    for i in range(3):
        w.client.post(f"{A}/users", json={"external_identity_id": f"p{i}", "username": f"pager0{i}", "display_name": "x",
                                          "email": f"pager0{i}@example.invalid"}, headers=h)
    assert w.client.get(f"{A}/audit-logs?action=user.create&limit=2", headers=h).json()["total"] == 3
    assert len(w.client.get(f"{A}/audit-logs?action=user.create&limit=2&offset=2", headers=h).json()["items"]) == 1
    assert w.client.get(f"{A}/audit-logs?outcome=NOPE", headers=h).status_code == 422
    sup = w.user("sup9", ["COLLECTION_SUPERVISOR"])
    assert w.client.get(f"{A}/audit-logs", headers=w.h(sup)).status_code == 403


def test_audit_details_redact_secrets(db):
    from app.domain.enums import ActorType
    from app.infrastructure import audit_repository as audit
    audit.record(db, audit.ActorContext(ActorType.SYSTEM, ref="t"), "x.y", details={"password": "hunter2", "ok": "fine"})
    db.flush()
    row = db.scalars(select(AuditLog).where(AuditLog.action == "x.y")).one()
    assert row.details == {"password": "[REDACTED]", "ok": "fine"}


# ----------------------------------------------------------------------------- migrations
def _cfg(url):
    cfg = Config(str(SVC / "alembic.ini"))
    cfg.set_main_option("script_location", str(SVC / "migrations"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture
def fresh_db():
    if not ADMIN_URL:
        pytest.skip("no TEST_DATABASE_URL")
    name = f"iam_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    from sqlalchemy.engine import make_url
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    yield url
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


def test_migrations_up_down_up_and_no_drift(fresh_db):
    cfg = _cfg(fresh_db)
    command.upgrade(cfg, "head")
    eng = create_engine(fresh_db)
    tables = set(inspect(eng).get_table_names(schema="iam"))
    expected = {"users", "roles", "permissions", "role_permissions", "role_conflicts", "user_roles", "teams", "team_members",
                "access_scopes", "user_access_scopes", "access_requests", "access_approvals", "audit_logs", "alembic_version_iam"}
    assert tables == expected
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"include_schemas": True, "version_table_schema": "iam",
                                                                    "include_object": lambda o, n, t, r, c: t != "table" or o.schema == "iam"}),
                                Base.metadata)
    assert diff == [], diff
    command.downgrade(cfg, "base")
    assert set(inspect(eng).get_table_names(schema="iam")) == {"alembic_version_iam"}
    command.upgrade(cfg, "head")
    assert "users" in inspect(eng).get_table_names(schema="iam")
    eng.dispose()


def test_migration_touches_only_the_iam_schema(fresh_db):
    eng = create_engine(fresh_db)
    with eng.begin() as c:
        c.execute(text("CREATE SCHEMA other_service"))
        c.execute(text("CREATE TABLE other_service.t (id int)"))
    command.upgrade(_cfg(fresh_db), "head")
    insp = inspect(eng)
    assert insp.get_table_names(schema="other_service") == ["t"]
    assert "alembic_version_iam" in insp.get_table_names(schema="iam")
    assert "alembic_version" not in insp.get_table_names(schema="public")
    eng.dispose()


# ----------------------------------------------------------------------------- seeding
def test_seed_catalog_is_idempotent(engine, db):
    from seed.identity import runner

    def snapshot():
        return {t: db.scalar(text(f"SELECT count(*) FROM iam.{t}")) for t in
                ("roles", "permissions", "role_permissions", "role_conflicts", "teams", "access_scopes")}
    first = snapshot()
    runner.seed_catalog(engine)
    runner.seed_catalog(engine)
    db.expire_all()
    assert snapshot() == first
    assert first["roles"] == 10 and first["teams"] == 3


def test_seed_roles_permissions_and_mappings(w, db):
    roles = {r.code: r for r in db.scalars(select(Role))}
    assert set(roles) == {"COLLECTION_AGENT", "COLLECTION_SUPERVISOR", "COLLECTION_MANAGER", "POLICY_ADMINISTRATOR",
                          "POLICY_APPROVER", "SYSTEM_ADMINISTRATOR", "RECOVERY_LEGAL_OFFICER", "HARDSHIP_OFFICER",
                          "COMPLIANCE_AUDITOR", "PORTFOLIO_EXECUTIVE"}
    assert {c for c, r in roles.items() if r.phase == "MVP"} == {"COLLECTION_AGENT", "COLLECTION_SUPERVISOR", "COLLECTION_MANAGER",
                                                                  "POLICY_ADMINISTRATOR", "POLICY_APPROVER", "SYSTEM_ADMINISTRATOR"}
    perms = {p.code for p in db.scalars(select(Permission))}
    for needed in ("policy.approve", "iam.user.create", "iam.access.approve", "case.read_team", "ptp.update", "recovery.review"):
        assert needed in perms

    def codes(role):
        return set(db.scalars(select(Permission.code).join(RolePermission).where(RolePermission.role_id == roles[role].id)))
    admin, agent = codes("SYSTEM_ADMINISTRATOR"), codes("COLLECTION_AGENT")
    assert not [c for c in admin if not c.startswith("iam.")]                    # IAM only
    assert not codes("POLICY_ADMINISTRATOR") & {"policy.approve", "policy.reject", "policy.activate"}   # maker != checker
    assert "policy.approve" in codes("POLICY_APPROVER") and "policy.create" not in codes("POLICY_APPROVER")
    assert not [c for c in agent if c.startswith(("iam.", "policy."))] and "case.read_portfolio" not in agent
    assert "iam.access.approve" not in codes("COLLECTION_SUPERVISOR")


def test_demo_seed_idempotent_and_environment_guarded(engine, db):
    from seed.identity import demo_users, runner
    from sqlalchemy.exc import SQLAlchemyError  # noqa: F401
    from seed.config import ConfigError

    with pytest.raises(ConfigError):
        runner.seed_demo_users(engine, app_env="production")
    assert db.scalar(text("SELECT count(*) FROM iam.users")) == 0
    n = runner.seed_demo_users(engine, app_env="development")
    runner.seed_demo_users(engine, app_env="development")
    db.expire_all()
    assert n == len(demo_users.DEMO_USERS) == db.scalar(text("SELECT count(*) FROM iam.users"))
    assert db.scalar(text("SELECT count(*) FROM iam.users WHERE email NOT LIKE '%@example.invalid'")) == 0
    assert db.scalar(text("SELECT count(*) FROM iam.user_roles")) == sum(len(u[2]) for u in demo_users.DEMO_USERS)
    # valid team assignments and scopes
    assert db.scalar(text("SELECT count(*) FROM iam.team_members WHERE member_role = 'LEAD'")) == 2
    # two separate administrators exist so maker-checker is exercisable, and no one holds conflicting roles
    assert db.scalar(text("SELECT count(*) FROM iam.user_roles ur JOIN iam.roles r ON r.id = ur.role_id "
                          "WHERE r.code = 'SYSTEM_ADMINISTRATOR'")) == 2
    assert db.scalar(text("""SELECT count(*) FROM iam.role_conflicts rc
        JOIN iam.user_roles a ON a.role_id = rc.role_a_id JOIN iam.user_roles b ON b.role_id = rc.role_b_id AND a.user_id = b.user_id""")) == 0


def test_bootstrap_admin_cli(engine, db):
    from typer.testing import CliRunner

    from app.cli import cli
    runner = CliRunner()
    args = ["bootstrap-admin", "--subject", "real-oidc-sub", "--username", "firstadmin", "--email", "First@Example.invalid",
            "--display-name", "First Admin"]
    res = runner.invoke(cli, args)
    assert res.exit_code == 0, res.output
    db.expire_all()
    u = db.scalar(select(User).where(User.username == "firstadmin"))
    assert u.email == "first@example.invalid"
    assert db.scalar(select(Role.code).join(UserRole).where(UserRole.user_id == u.id)) == "SYSTEM_ADMINISTRATOR"
    assert runner.invoke(cli, args).exit_code == 1            # no duplicates
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "user.bootstrap_admin")) == 1
