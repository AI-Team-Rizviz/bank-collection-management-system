from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.domain.models import User, UserRole


def utcnow() -> datetime:
    return datetime.now(UTC)


def paginate(db: Session, stmt, limit: int, offset: int):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return list(db.scalars(stmt.limit(limit).offset(offset)).unique()), total or 0


def insert_or_conflict(db: Session, obj: Any, message: str) -> None:
    """Insert inside a SAVEPOINT so a unique-violation (e.g. a concurrent duplicate) becomes a clean 409
    without poisoning the surrounding transaction."""
    try:
        with db.begin_nested():
            db.add(obj)
            db.flush()
    except IntegrityError as exc:
        raise Conflict(message) from exc


def get_or_404(db: Session, model, ident: uuid.UUID, what: str, *, for_update: bool = False):
    obj = db.get(model, ident, with_for_update=for_update)
    if obj is None:
        raise NotFound(f"{what} not found")
    return obj


def check_future(valid_until: datetime | None) -> None:
    if valid_until is not None and valid_until <= utcnow():
        raise BadRequest("valid_until must be in the future")


def bump_authz_version(db: Session, user_ids) -> None:
    ids = list(user_ids)
    if ids:
        db.execute(update(User).where(User.id.in_(ids)).values(authz_version=User.authz_version + 1))


def bump_role_holders(db: Session, role_id: uuid.UUID) -> None:
    """A change to a role's definition affects everyone currently holding it."""
    holders = select(UserRole.user_id).where(UserRole.role_id == role_id, UserRole.status == "ACTIVE")
    db.execute(update(User).where(User.id.in_(holders)).values(authz_version=User.authz_version + 1))
