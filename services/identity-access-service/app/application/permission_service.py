"""Permission catalog (read-only via API) and role-permission mappings."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.common import bump_role_holders, get_or_404, insert_or_conflict, paginate
from app.core.exceptions import ApprovalRequired, Conflict, Forbidden, NotFound
from app.domain import policies
from app.domain.models import Permission, Role, RolePermission, UserRole
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext


def list_permissions(db: Session, *, category: str | None, is_sensitive: bool | None, q: str | None,
                     limit: int, offset: int):
    stmt = select(Permission).order_by(Permission.code)
    if category:
        stmt = stmt.where(Permission.category == category)
    if is_sensitive is not None:
        stmt = stmt.where(Permission.is_sensitive == is_sensitive)
    if q:
        stmt = stmt.where(Permission.code.like(q.lower().replace("%", r"\%") + "%"))
    return paginate(db, stmt, limit, offset)


def list_role_permissions(db: Session, role_id: uuid.UUID) -> list[Permission]:
    get_or_404(db, Role, role_id, "Role")
    stmt = (select(Permission).join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id).order_by(Permission.code))
    return list(db.scalars(stmt))


def _guard_direct(db: Session, ctx: ActorContext, role: Role, perm: Permission, action: str) -> None:
    holds_role = db.scalar(select(UserRole.id).where(
        UserRole.user_id == ctx.user_id, UserRole.role_id == role.id, UserRole.status == "ACTIVE"))
    if holds_role:
        audit.record_independent(ctx, action, target_type="role", target_id=role.id,
                                 details={"permission": perm.code, "reason": "self_escalation"})
        raise Forbidden("You cannot change the permissions of a role you hold")
    if policies.role_permission_change_needs_approval(role_is_system=role.is_system,
                                                      permission_is_sensitive=perm.is_sensitive):
        audit.record_independent(ctx, action, target_type="role", target_id=role.id,
                                 details={"permission": perm.code, "reason": "approval_required"})
        raise ApprovalRequired("This change requires an approved access request")


def grant_role_permission(db: Session, ctx: ActorContext, role_id: uuid.UUID, permission_id: uuid.UUID, *,
                          source_request_id: uuid.UUID | None = None) -> Permission:
    role = get_or_404(db, Role, role_id, "Role", for_update=True)
    perm = get_or_404(db, Permission, permission_id, "Permission")
    if source_request_id is None:
        _guard_direct(db, ctx, role, perm, "role_permission.grant")
    if role.status != "ACTIVE":
        raise Conflict("Role is not active")
    insert_or_conflict(db, RolePermission(role_id=role.id, permission_id=perm.id, granted_by=ctx.user_id,
                                          source_request_id=source_request_id), "Role already has this permission")
    bump_role_holders(db, role.id)
    audit.record(db, ctx, "role_permission.grant", target_type="role", target_id=role.id,
                 details={"permission": perm.code, "via_request": str(source_request_id) if source_request_id else None})
    return perm


def revoke_role_permission(db: Session, ctx: ActorContext, role_id: uuid.UUID, permission_id: uuid.UUID, *,
                           source_request_id: uuid.UUID | None = None) -> None:
    role = get_or_404(db, Role, role_id, "Role", for_update=True)
    perm = get_or_404(db, Permission, permission_id, "Permission")
    if source_request_id is None and role.is_system:  # removing rights from a custom role is not an escalation
        audit.record_independent(ctx, "role_permission.revoke", target_type="role", target_id=role.id,
                                 details={"permission": perm.code, "reason": "approval_required"})
        raise ApprovalRequired("Changing a system role requires an approved access request")
    link = db.get(RolePermission, (role.id, perm.id))
    if link is None:
        raise NotFound("Role does not have this permission")
    db.delete(link)
    db.flush()
    bump_role_holders(db, role.id)
    audit.record(db, ctx, "role_permission.revoke", target_type="role", target_id=role.id,
                 details={"permission": perm.code, "via_request": str(source_request_id) if source_request_id else None})
