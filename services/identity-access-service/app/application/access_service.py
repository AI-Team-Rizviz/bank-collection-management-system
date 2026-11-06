"""Maker-checker: access requests, independent approval, and transactional application of the change."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application import permission_service, role_service, scope_service
from app.application.common import get_or_404, paginate, utcnow
from app.core.exceptions import AppError, Conflict, Forbidden, NotFound
from app.domain.enums import RequestStatus, RequestType
from app.domain.models import (
    AccessApproval,
    AccessRequest,
    AccessScope,
    Permission,
    Role,
    RolePermission,
    User,
    UserAccessScope,
    UserRole,
)
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext


def _validate_request(db: Session, data) -> None:
    """Reject requests that could never be applied, so approvers only see meaningful decisions."""
    t = data.request_type
    if t in (RequestType.ASSIGN_ROLE, RequestType.GRANT_SCOPE):
        target = get_or_404(db, User, data.target_user_id, "Target user")
        if target.status != "ACTIVE":
            raise Conflict("Target user is not active")
    if t is RequestType.ASSIGN_ROLE:
        role = get_or_404(db, Role, data.role_id, "Role")
        if role.status != "ACTIVE":
            raise Conflict("Role is not active")
        if db.scalar(select(UserRole.id).where(UserRole.user_id == data.target_user_id, UserRole.role_id == role.id,
                                               UserRole.status == "ACTIVE")):
            raise Conflict("User already holds this role")
        if role_service._conflicting_roles(db, data.target_user_id, role.id):
            raise Conflict("Role conflicts with a role the user already holds", code="role_conflict")
    elif t is RequestType.GRANT_SCOPE:
        scope = get_or_404(db, AccessScope, data.scope_id, "Scope")
        if scope.status != "ACTIVE":
            raise Conflict("Scope is not active")
        if db.scalar(select(UserAccessScope.id).where(UserAccessScope.user_id == data.target_user_id,
                                                      UserAccessScope.scope_id == scope.id,
                                                      UserAccessScope.status == "ACTIVE")):
            raise Conflict("User already holds this scope")
    else:
        get_or_404(db, Role, data.role_id, "Role")
        get_or_404(db, Permission, data.permission_id, "Permission")
        linked = db.get(RolePermission, (data.role_id, data.permission_id)) is not None
        if t is RequestType.GRANT_ROLE_PERMISSION and linked:
            raise Conflict("Role already has this permission")
        if t is RequestType.REVOKE_ROLE_PERMISSION and not linked:
            raise Conflict("Role does not have this permission")


def create_request(db: Session, ctx: ActorContext, data) -> AccessRequest:
    if ctx.user_id is None:
        raise Forbidden("Only users can create access requests")
    _validate_request(db, data)
    dup = db.scalar(select(AccessRequest.id).where(
        AccessRequest.status == "PENDING", AccessRequest.request_type == data.request_type.value,
        AccessRequest.target_user_id.is_not_distinct_from(data.target_user_id),
        AccessRequest.role_id.is_not_distinct_from(data.role_id),
        AccessRequest.permission_id.is_not_distinct_from(data.permission_id),
        AccessRequest.scope_id.is_not_distinct_from(data.scope_id)))
    if dup:
        raise Conflict("An identical request is already pending")
    req = AccessRequest(request_type=data.request_type.value, requested_by=ctx.user_id,
                        target_user_id=data.target_user_id, role_id=data.role_id, permission_id=data.permission_id,
                        scope_id=data.scope_id, valid_until=data.valid_until, justification=data.justification)
    db.add(req)
    db.flush()
    audit.record(db, ctx, "access_request.create", target_type="access_request", target_id=req.id,
                 details={"type": req.request_type, "target_user_id": req.target_user_id})
    return req


def get_request(db: Session, request_id: uuid.UUID) -> AccessRequest:
    return get_or_404(db, AccessRequest, request_id, "Access request")


def list_requests(db: Session, *, status: str | None, request_type: str | None, requested_by: uuid.UUID | None,
                  limit: int, offset: int):
    stmt = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if status:
        stmt = stmt.where(AccessRequest.status == status)
    if request_type:
        stmt = stmt.where(AccessRequest.request_type == request_type)
    if requested_by:
        stmt = stmt.where(AccessRequest.requested_by == requested_by)
    return paginate(db, stmt, limit, offset)


def _lock_pending(db: Session, ctx: ActorContext, request_id: uuid.UUID) -> AccessRequest:
    req = db.get(AccessRequest, request_id, with_for_update=True)  # serialises concurrent decisions
    if req is None:
        raise NotFound("Access request not found")
    if ctx.user_id in (req.requested_by, req.target_user_id):
        audit.record_independent(ctx, "access_request.decide",
                                 target_type="access_request", target_id=req.id,
                                 details={"reason": "separation_of_duties"})
        raise Forbidden("Requesters and beneficiaries cannot decide their own access request",
                        code="separation_of_duties")
    if req.status != RequestStatus.PENDING.value:
        raise Conflict("Access request has already been decided", code="request_not_pending")
    return req


def _apply(db: Session, ctx: ActorContext, req: AccessRequest) -> None:
    t = RequestType(req.request_type)
    if t is RequestType.ASSIGN_ROLE:
        role_service.assign_role(db, ctx, req.target_user_id, req.role_id, valid_until=req.valid_until,
                                 source_request_id=req.id)
    elif t is RequestType.GRANT_SCOPE:
        scope_service.grant_scope(db, ctx, req.target_user_id, req.scope_id, valid_until=req.valid_until,
                                  source_request_id=req.id)
    elif t is RequestType.GRANT_ROLE_PERMISSION:
        permission_service.grant_role_permission(db, ctx, req.role_id, req.permission_id, source_request_id=req.id)
    else:
        permission_service.revoke_role_permission(db, ctx, req.role_id, req.permission_id, source_request_id=req.id)


def approve(db: Session, ctx: ActorContext, request_id: uuid.UUID, comment: str | None) -> AccessRequest:
    req = _lock_pending(db, ctx, request_id)
    db.add(AccessApproval(request_id=req.id, approver_id=ctx.user_id, decision="APPROVED", comment=comment))
    req.decided_at = utcnow()
    try:
        with db.begin_nested():  # the change and its status flip commit together, or the change is undone
            _apply(db, ctx, req)
            req.status, req.applied_at = RequestStatus.APPLIED.value, utcnow()
    except AppError as exc:
        # State changed since the request was made (e.g. user deactivated); record it, apply nothing.
        req.status, req.failure_reason = RequestStatus.FAILED.value, exc.code
        audit.record(db, ctx, "access_request.apply", target_type="access_request", target_id=req.id,
                     outcome=audit.AuditOutcome.FAILURE, details={"reason": exc.code})
    else:
        audit.record(db, ctx, "access_request.approve", target_type="access_request", target_id=req.id,
                     details={"type": req.request_type})
    db.flush()
    db.expire(req, ["approvals"])  # include the decision just recorded in the response
    return req


def reject(db: Session, ctx: ActorContext, request_id: uuid.UUID, comment: str | None) -> AccessRequest:
    req = _lock_pending(db, ctx, request_id)
    db.add(AccessApproval(request_id=req.id, approver_id=ctx.user_id, decision="REJECTED", comment=comment))
    req.status, req.decided_at = RequestStatus.REJECTED.value, utcnow()
    db.flush()
    audit.record(db, ctx, "access_request.reject", target_type="access_request", target_id=req.id,
                 details={"type": req.request_type})
    db.expire(req, ["approvals"])
    return req

