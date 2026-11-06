"""Roles and user-role assignments."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.application.common import (
    bump_authz_version,
    bump_role_holders,
    check_future,
    get_or_404,
    insert_or_conflict,
    paginate,
    utcnow,
)
from app.core.exceptions import ApprovalRequired, Conflict, Forbidden, NotFound
from app.domain import policies
from app.domain.models import Role, RoleConflict, User, UserRole
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext


# ------------------------------------------------------------------ roles
def create_role(db: Session, ctx: ActorContext, data) -> Role:
    role = Role(code=data.code, name=data.name, description=data.description, is_system=False, is_privileged=False,
                phase="MVP", created_by=ctx.user_id, updated_by=ctx.user_id)
    insert_or_conflict(db, role, "A role with this code already exists")
    audit.record(db, ctx, "role.create", target_type="role", target_id=role.id, details={"code": role.code})
    return role


def get_role(db: Session, role_id: uuid.UUID) -> Role:
    return get_or_404(db, Role, role_id, "Role")


def list_roles(db: Session, *, status: str | None, is_system: bool | None, limit: int, offset: int):
    stmt = select(Role).order_by(Role.code)
    if status:
        stmt = stmt.where(Role.status == status)
    if is_system is not None:
        stmt = stmt.where(Role.is_system == is_system)
    return paginate(db, stmt, limit, offset)


def update_role(db: Session, ctx: ActorContext, role_id: uuid.UUID, patch) -> Role:
    role = get_or_404(db, Role, role_id, "Role", for_update=True)
    changes = patch.model_dump(exclude_unset=True)
    if role.is_system and (set(changes) - {"description"}):
        audit.record_independent(ctx, "role.update", target_type="role", target_id=role.id,
                                 details={"reason": "system_role_protected"})
        raise Conflict("System roles are protected: only the description can be changed", code="system_role_protected")
    for k, v in changes.items():
        setattr(role, k, v)
    role.updated_by = ctx.user_id
    if "status" in changes:
        bump_role_holders(db, role.id)
    db.flush()
    audit.record(db, ctx, "role.update", target_type="role", target_id=role.id, details={"fields": ",".join(changes)})
    return role


# ------------------------------------------------------------------ user <-> role
def list_user_roles(db: Session, user_id: uuid.UUID, *, include_revoked: bool = False) -> list[UserRole]:
    get_or_404(db, User, user_id, "User")
    stmt = select(UserRole).where(UserRole.user_id == user_id).order_by(UserRole.created_at)
    if not include_revoked:
        stmt = stmt.where(UserRole.status == "ACTIVE")
    return list(db.scalars(stmt).unique())


def _conflicting_roles(db: Session, user_id: uuid.UUID, role_id: uuid.UUID) -> list[str]:
    held = select(UserRole.role_id).where(UserRole.user_id == user_id, UserRole.status == "ACTIVE")
    pairs = select(RoleConflict).where(
        or_(
            (RoleConflict.role_a_id == role_id) & RoleConflict.role_b_id.in_(held),
            (RoleConflict.role_b_id == role_id) & RoleConflict.role_a_id.in_(held),
        )
    )
    others = {c.role_b_id if c.role_a_id == role_id else c.role_a_id for c in db.scalars(pairs)}
    return [r.code for r in db.scalars(select(Role).where(Role.id.in_(others)))] if others else []


def assign_role(db: Session, ctx: ActorContext, user_id: uuid.UUID, role_id: uuid.UUID, *,
                valid_until: datetime | None = None, source_request_id: uuid.UUID | None = None) -> UserRole:
    """Direct assignment (source_request_id is None) or the application step of an approved request."""
    via_request = source_request_id is not None
    user = get_or_404(db, User, user_id, "User", for_update=True)
    role = get_or_404(db, Role, role_id, "Role")
    if not via_request:
        if ctx.user_id == user_id:
            audit.record_independent(ctx, "user_role.assign", target_type="user", target_id=user_id,
                                     details={"role": role.code, "reason": "self_assignment"})
            raise Forbidden("You cannot assign roles to yourself")
        if policies.role_needs_approval(is_privileged=role.is_privileged):
            audit.record_independent(ctx, "user_role.assign", target_type="user", target_id=user_id,
                                     details={"role": role.code, "reason": "approval_required"})
            raise ApprovalRequired("Privileged roles require an approved access request")
    if user.status != "ACTIVE":
        raise Conflict("User is not active")
    if role.status != "ACTIVE":
        raise Conflict("Role is not active")
    check_future(valid_until)
    clash = _conflicting_roles(db, user_id, role_id)
    if clash:
        raise Conflict(f"Role conflicts with already assigned role(s): {', '.join(sorted(clash))}", code="role_conflict")
    ur = UserRole(user_id=user_id, role_id=role_id, valid_until=valid_until, assigned_by=ctx.user_id,
                  source_request_id=source_request_id)
    insert_or_conflict(db, ur, "User already holds this role")
    bump_authz_version(db, [user_id])
    ur.role = role
    audit.record(db, ctx, "user_role.assign", target_type="user", target_id=user_id,
                 details={"role": role.code, "via_request": str(source_request_id) if via_request else None})
    return ur


def revoke_role(db: Session, ctx: ActorContext, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
    get_or_404(db, User, user_id, "User", for_update=True)
    ur = db.scalars(select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id,
                                          UserRole.status == "ACTIVE")).unique().first()
    if ur is None:
        raise NotFound("Role assignment not found")
    ur.status, ur.revoked_by, ur.revoked_at = "REVOKED", ctx.user_id, utcnow()
    bump_authz_version(db, [user_id])
    audit.record(db, ctx, "user_role.revoke", target_type="user", target_id=user_id, details={"role": ur.role.code})
