"""Idempotent IAM seeding. Re-running never duplicates rows; catalog definitions are refreshed in place."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from sqlalchemy import Engine, MetaData, Table, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from seed.config import PROJECT_ROOT, ConfigError, _read_env_file
from seed.identity import demo_users, permissions, role_permissions, roles, teams

SCHEMA = "iam"
IAM_ENV = PROJECT_ROOT.parent / "services" / "identity-access-service" / ".env"
DEMO_ENVS = {"development", "test"}
DEMO_PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "DemoPass!2345")  # development-only; every demo user shares it


def _hash_password(password: str) -> str:
    """Same format as the IAM service (app/core/passwords.py): scrypt$n$r$p$salt$hash."""
    n, r, p = 2**14, 8, 1
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def iam_settings() -> dict[str, str]:
    file_vals = _read_env_file(IAM_ENV)
    return {k: os.environ.get(k) or file_vals.get(k, "") for k in ("IAM_DATABASE_URL", "DATABASE_URL", "APP_ENV")}


def get_iam_engine() -> Engine:
    """IAM runtime credentials: IAM_DATABASE_URL env, else the IAM service's own .env. (Deliberately NOT data_seed's
    DATABASE_URL, which belongs to a different database role.)"""
    cfg = iam_settings()
    raw = cfg["IAM_DATABASE_URL"] or _read_env_file(IAM_ENV).get("DATABASE_URL", "")
    if not raw:
        raise ConfigError("IAM database URL not found: set IAM_DATABASE_URL or services/identity-access-service/.env")
    for scheme in ("postgresql://", "postgres://"):
        if raw.startswith(scheme):
            raw = "postgresql+psycopg://" + raw[len(scheme):]
    return create_engine(make_url(raw), pool_pre_ping=True)


def _tables(engine: Engine) -> dict[str, Table]:
    md = MetaData()
    names = ["roles", "permissions", "role_permissions", "role_conflicts", "access_scopes", "teams", "users",
             "user_roles", "team_members", "user_access_scopes", "audit_logs"]
    return {n: Table(n, md, schema=SCHEMA, autoload_with=engine) for n in names}


def _ids(conn, table: Table, key: str) -> dict[str, object]:
    return {r[0]: r[1] for r in conn.execute(select(table.c[key], table.c.id))}


def seed_catalog(engine: Engine) -> dict[str, int]:
    """Roles, permissions, mappings, conflicts, sample teams and scopes. Safe for every environment."""
    t = _tables(engine)
    with engine.begin() as conn:
        for code, name, desc, phase, privileged in roles.ROLES:
            stmt = insert(t["roles"]).values(code=code, name=name, description=desc, phase=phase, is_system=True,
                                             is_privileged=privileged)
            # status is deliberately not overwritten: a deactivated system role stays deactivated.
            conn.execute(stmt.on_conflict_do_update(index_elements=["code"], set_=dict(
                name=stmt.excluded.name, description=stmt.excluded.description, phase=stmt.excluded.phase,
                is_system=True, is_privileged=stmt.excluded.is_privileged, updated_at=func.now())))
        for code, desc, category, sensitive, scope_types in permissions.PERMISSIONS:
            stmt = insert(t["permissions"]).values(code=code, description=desc, category=category,
                                                   is_sensitive=sensitive, allowed_scope_types=scope_types)
            conn.execute(stmt.on_conflict_do_update(index_elements=["code"], set_=dict(
                description=stmt.excluded.description, category=stmt.excluded.category,
                is_sensitive=stmt.excluded.is_sensitive, allowed_scope_types=stmt.excluded.allowed_scope_types,
                updated_at=func.now())))
        rid, pid = _ids(conn, t["roles"], "code"), _ids(conn, t["permissions"], "code")
        for rcode, pcodes in role_permissions.ROLE_PERMISSIONS.items():
            for pcode in pcodes:
                conn.execute(insert(t["role_permissions"]).values(role_id=rid[rcode], permission_id=pid[pcode])
                             .on_conflict_do_nothing())
        for a, b, reason in roles.ROLE_CONFLICTS:
            lo, hi = sorted((rid[a], rid[b]), key=str)
            conn.execute(insert(t["role_conflicts"]).values(role_a_id=lo, role_b_id=hi, reason=reason)
                         .on_conflict_do_nothing())
        for code, name, branch, region in teams.TEAMS:
            conn.execute(insert(t["teams"]).values(code=code, name=name, branch_id=branch, region_id=region)
                         .on_conflict_do_nothing(index_elements=["code"]))
        scopes = list(teams.SCOPES) + [("TEAM", c, f"Team {n}") for c, n, *_ in teams.TEAMS]
        for stype, value, name in scopes:
            conn.execute(insert(t["access_scopes"]).values(scope_type=stype, scope_value=value, name=name)
                         .on_conflict_do_nothing())
        conn.execute(insert(t["audit_logs"]).values(actor_type="SYSTEM", actor_ref="seed.identity", action="seed.catalog",
                                                    outcome="SUCCESS", details={"roles": len(roles.ROLES),
                                                                                "permissions": len(permissions.PERMISSIONS)}))
    return {"roles": len(roles.ROLES), "permissions": len(permissions.PERMISSIONS),
            "teams": len(teams.TEAMS), "scopes": len(scopes)}


def seed_demo_users(engine: Engine, *, app_env: str | None = None) -> int:
    """Fictional development users. Refuses to run unless APP_ENV is development/test."""
    env = app_env if app_env is not None else iam_settings()["APP_ENV"]
    if env not in DEMO_ENVS:
        raise ConfigError(f"Refusing to seed demo users: APP_ENV={env!r} (allowed: {sorted(DEMO_ENVS)})")
    t = _tables(engine)
    pw_hash = _hash_password(DEMO_PASSWORD)
    with engine.begin() as conn:
        rid, tid = _ids(conn, t["roles"], "code"), _ids(conn, t["teams"], "code")
        scope_ids = {(r.scope_type, r.scope_value): r.id for r in conn.execute(select(t["access_scopes"]))}
        for username, display, role_codes, memberships, scopes in demo_users.DEMO_USERS:
            conn.execute(insert(t["users"]).values(
                external_identity_id=demo_users.external_id(username), username=username, display_name=display,
                email=demo_users.email(username), password_hash=pw_hash).on_conflict_do_nothing(index_elements=["username"]))
            conn.execute(t["users"].update().where((t["users"].c.username == username) & t["users"].c.password_hash.is_(None))
                         .values(password_hash=pw_hash))
            uid = conn.execute(select(t["users"].c.id).where(t["users"].c.username == username)).scalar_one()
            for rc in role_codes:  # partial unique index (active) makes this idempotent
                conn.execute(insert(t["user_roles"]).values(user_id=uid, role_id=rid[rc], assigned_by=None)
                             .on_conflict_do_nothing())
            for team_code, member_role in memberships:
                conn.execute(insert(t["team_members"]).values(team_id=tid[team_code], user_id=uid, member_role=member_role)
                             .on_conflict_do_nothing())
            for key in scopes:
                conn.execute(insert(t["user_access_scopes"]).values(user_id=uid, scope_id=scope_ids[key])
                             .on_conflict_do_nothing())
        conn.execute(insert(t["audit_logs"]).values(actor_type="SYSTEM", actor_ref="seed.identity", action="seed.demo_users",
                                                    outcome="SUCCESS", details={"users": len(demo_users.DEMO_USERS)}))
    return len(demo_users.DEMO_USERS)


__all__ = ["seed_catalog", "seed_demo_users", "get_iam_engine"]
