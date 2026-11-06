from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.common import (
    bump_authz_version,
    check_future,
    get_or_404,
    insert_or_conflict,
    paginate,
    utcnow,
)
from app.core.exceptions import ApprovalRequired, Conflict, Forbidden, NotFound
from app.domain import policies
from app.domain.models import AccessScope, Team, User, UserAccessScope
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext


def list_scopes(db: Session, *, scope_type: str | None, limit: int, offset: int):
    stmt = select(AccessScope).order_by(AccessScope.scope_type, AccessScope.scope_value)
    if scope_type:
        stmt = stmt.where(AccessScope.scope_type == scope_type)
    return paginate(db, stmt, limit, offset)


def create_scope(db: Session, ctx: ActorContext, data) -> AccessScope:
    if data.scope_type == "TEAM" and not db.scalar(select(Team.id).where(Team.code == data.scope_value)):
        raise Conflict("TEAM scopes must reference an existing team code", code="unknown_team")
    scope = AccessScope(scope_type=data.scope_type, scope_value=data.scope_value, name=data.name, created_by=ctx.user_id)
    insert_or_conflict(db, scope, "This scope already exists")
    audit.record(db, ctx, "scope.create", target_type="scope", target_id=scope.id,
                 details={"type": scope.scope_type, "value": scope.scope_value})
    return scope


def ensure_team_scope(db: Session, ctx: ActorContext, team: Team) -> None:
    exists = db.scalar(select(AccessScope.id).where(AccessScope.scope_type == "TEAM", AccessScope.scope_value == team.code))
    if not exists:
        db.add(AccessScope(scope_type="TEAM", scope_value=team.code, name=f"Team {team.name}", created_by=ctx.user_id))
        db.flush()


def list_user_scopes(db: Session, user_id: uuid.UUID) -> list[UserAccessScope]:
    get_or_404(db, User, user_id, "User")
    return list(db.scalars(select(UserAccessScope).where(UserAccessScope.user_id == user_id,
                                                         UserAccessScope.status == "ACTIVE")).unique())


def grant_scope(db: Session, ctx: ActorContext, user_id: uuid.UUID, scope_id: uuid.UUID, *,
                valid_until: datetime | None = None, source_request_id: uuid.UUID | None = None) -> UserAccessScope:
    via_request = source_request_id is not None
    user = get_or_404(db, User, user_id, "User", for_update=True)
    scope = get_or_404(db, AccessScope, scope_id, "Scope")
    if not via_request:
        if ctx.user_id == user_id:
            audit.record_independent(ctx, "user_scope.grant", target_type="user", target_id=user_id,
                                     details={"scope": scope.scope_type, "reason": "self_assignment"})
            raise Forbidden("You cannot grant scopes to yourself")
        if policies.scope_needs_approval(scope.scope_type):
            audit.record_independent(ctx, "user_scope.grant", target_type="user", target_id=user_id,
                                     details={"scope": scope.scope_type, "reason": "approval_required"})
            raise ApprovalRequired("Widening data scope (REGION/PORTFOLIO/GLOBAL) requires an approved access request")
    if user.status != "ACTIVE" or scope.status != "ACTIVE":
        raise Conflict("User and scope must be active")
    check_future(valid_until)
    grant = UserAccessScope(user_id=user_id, scope_id=scope_id, valid_until=valid_until, granted_by=ctx.user_id,
                            source_request_id=source_request_id)
    insert_or_conflict(db, grant, "User already holds this scope")
    grant.scope = scope
    bump_authz_version(db, [user_id])
    audit.record(db, ctx, "user_scope.grant", target_type="user", target_id=user_id,
                 details={"type": scope.scope_type, "value": scope.scope_value,
                          "via_request": str(source_request_id) if via_request else None})
    return grant


def revoke_scope(db: Session, ctx: ActorContext, user_id: uuid.UUID, scope_id: uuid.UUID) -> None:
    get_or_404(db, User, user_id, "User", for_update=True)
    g = db.scalars(select(UserAccessScope).where(UserAccessScope.user_id == user_id,
                                                 UserAccessScope.scope_id == scope_id,
                                                 UserAccessScope.status == "ACTIVE")).unique().first()
    if g is None:
        raise NotFound("Scope assignment not found")
    g.status, g.revoked_by, g.revoked_at = "REVOKED", ctx.user_id, utcnow()
    bump_authz_version(db, [user_id])
    audit.record(db, ctx, "user_scope.revoke", target_type="user", target_id=user_id,
                 details={"type": g.scope.scope_type, "value": g.scope.scope_value})
