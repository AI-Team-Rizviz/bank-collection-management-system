"""Effective-permission resolution and the authorization decision used by IAM itself and by other services."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.application.common import utcnow
from app.core.config import get_settings
from app.domain import policies
from app.domain.models import AccessScope, Permission, Role, RolePermission, User, UserAccessScope, UserRole
from app.domain.policies import AuthzDecision, PermissionGrant, ScopeGrant


@dataclass
class Effective:
    user: User
    roles: list[str]
    grants: dict[str, PermissionGrant]
    scopes: list[ScopeGrant]


def _grants(db: Session, user_id: uuid.UUID, now: datetime) -> dict[str, PermissionGrant]:
    stmt = (
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, UserRole.status == "ACTIVE", Role.status == "ACTIVE",
               UserRole.valid_from <= now, or_(UserRole.valid_until.is_(None), UserRole.valid_until > now))
    )
    return {
        p.code: PermissionGrant(p.code, p.is_sensitive, tuple(p.allowed_scope_types) if p.allowed_scope_types is not None else None)
        for p in db.scalars(stmt).unique()
    }


def effective_access(db: Session, user: User, now: datetime | None = None) -> Effective:
    now = now or utcnow()
    role_stmt = (select(Role.code).join(UserRole, UserRole.role_id == Role.id)
                 .where(UserRole.user_id == user.id, UserRole.status == "ACTIVE", Role.status == "ACTIVE",
                        UserRole.valid_from <= now, or_(UserRole.valid_until.is_(None), UserRole.valid_until > now))
                 .order_by(Role.code))
    scope_stmt = (select(AccessScope).join(UserAccessScope, UserAccessScope.scope_id == AccessScope.id)
                  .where(UserAccessScope.user_id == user.id, UserAccessScope.status == "ACTIVE",
                         AccessScope.status == "ACTIVE", UserAccessScope.valid_from <= now,
                         or_(UserAccessScope.valid_until.is_(None), UserAccessScope.valid_until > now)))
    return Effective(
        user=user,
        roles=list(db.scalars(role_stmt)),
        grants=_grants(db, user.id, now),
        scopes=[ScopeGrant(s.scope_type, s.scope_value) for s in db.scalars(scope_stmt)],
    )


def has_permission(db: Session, user: User, permission: str) -> bool:
    return user.status == "ACTIVE" and permission in _grants(db, user.id, utcnow())


def find_user(db: Session, *, user_id: uuid.UUID | None = None, subject: str | None = None) -> User | None:
    if user_id is not None:
        return db.get(User, user_id)
    return db.scalar(select(User).where(User.external_identity_id == subject))


def check(db: Session, *, user_id: uuid.UUID | None, subject: str | None, permission: str,
          resource: dict[str, Any] | None) -> dict[str, Any]:
    """Authoritative decision. Unknown and inactive users get the same generic denial."""
    settings = get_settings()
    now = utcnow()
    user = find_user(db, user_id=user_id, subject=subject)
    base = {"permission": permission, "evaluated_at": now, "cache_ttl_seconds": 0}
    if user is None or user.status != "ACTIVE":
        return {**base, "allowed": False, "reason": "user_not_authorized", "user_id": user.id if user else None,
                "authz_version": None, "matched_scope": None}
    eff = effective_access(db, user, now)
    decision: AuthzDecision = policies.evaluate(user_id=user.id, permission=permission, grants=eff.grants,
                                                scopes=eff.scopes, resource=resource)
    grant = eff.grants.get(permission)
    # Sensitive permissions must always be re-checked live; only non-sensitive ALLOW decisions may be cached.
    ttl = settings.authz_cache_ttl_seconds if (decision.allowed and grant and not grant.is_sensitive) else 0
    return {**base, "allowed": decision.allowed, "reason": decision.reason, "user_id": user.id,
            "authz_version": user.authz_version, "cache_ttl_seconds": ttl,
            "matched_scope": ({"scope_type": decision.matched_scope.scope_type,
                               "scope_value": decision.matched_scope.scope_value} if decision.matched_scope else None)}
