from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.common import bump_authz_version, get_or_404, insert_or_conflict, paginate, utcnow
from app.core.config import get_settings
from app.core.exceptions import BadRequest, Conflict, Forbidden
from app.domain.models import User
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext


def create_user(db: Session, ctx: ActorContext, data) -> User:
    if data.external_identity_id in get_settings().service_subjects:
        raise BadRequest("external_identity_id is reserved")
    user = User(external_identity_id=data.external_identity_id, username=data.username,
                display_name=data.display_name, email=data.email, created_by=ctx.user_id, updated_by=ctx.user_id)
    insert_or_conflict(db, user, "A user with the same identity, username or email already exists")
    audit.record(db, ctx, "user.create", target_type="user", target_id=user.id, details={"username": user.username})
    return user


def get_user(db: Session, user_id: uuid.UUID) -> User:
    return get_or_404(db, User, user_id, "User")


def list_users(db: Session, *, status: str | None, q: str | None, limit: int, offset: int):
    stmt = select(User).order_by(User.username)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        like = q.lower().replace("%", r"\%").replace("_", r"\_") + "%"
        stmt = stmt.where(or_(User.username.like(like), User.email.like(like)))
    return paginate(db, stmt, limit, offset)


def update_user(db: Session, ctx: ActorContext, user_id: uuid.UUID, patch) -> User:
    user = get_or_404(db, User, user_id, "User")
    changes = patch.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(user, k, v)
    user.updated_by = ctx.user_id
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise Conflict("A user with the same email already exists") from exc
    audit.record(db, ctx, "user.update", target_type="user", target_id=user.id, details={"fields": ",".join(changes)})
    return user


def deactivate_user(db: Session, ctx: ActorContext, user_id: uuid.UUID) -> User:
    if ctx.user_id == user_id:
        audit.record_independent(ctx, "user.deactivate", target_type="user", target_id=user_id,
                                 details={"reason": "self_deactivation"})
        raise Forbidden("You cannot deactivate your own account")
    user = get_or_404(db, User, user_id, "User")
    if user.status == "INACTIVE":
        raise Conflict("User is already inactive")
    user.status, user.deactivated_at, user.updated_by = "INACTIVE", utcnow(), ctx.user_id
    bump_authz_version(db, [user.id])
    audit.record(db, ctx, "user.deactivate", target_type="user", target_id=user.id)
    return user


def reactivate_user(db: Session, ctx: ActorContext, user_id: uuid.UUID) -> User:
    user = get_or_404(db, User, user_id, "User")
    if user.status == "ACTIVE":
        raise Conflict("User is already active")
    user.status, user.deactivated_at, user.updated_by = "ACTIVE", None, ctx.user_id
    bump_authz_version(db, [user.id])
    audit.record(db, ctx, "user.reactivate", target_type="user", target_id=user.id)
    return user
