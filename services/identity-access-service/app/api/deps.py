"""Authentication (token -> principal) and permission-enforcing dependencies."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application import authorization_service
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, Forbidden, Unauthenticated
from app.core.security import Principal
from app.domain.enums import ActorType, AuditOutcome
from app.domain.models import User
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext
from app.infrastructure.tokens import InvalidToken

bearer = HTTPBearer(auto_error=False, description="Access token returned by POST /api/v1/auth/login")


class NotConfigured(AppError):
    status_code, code = 503, "authentication_unavailable"


@dataclass
class Caller:
    principal: Principal
    user: User | None
    ctx: ActorContext


def pagination(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> tuple[int, int]:
    return limit, offset


def _ctx(request: Request, actor_type: ActorType, user_id=None, ref=None) -> ActorContext:
    ip = request.client.host if request.client else None
    try:  # only well-formed addresses reach the INET audit column (unix sockets, proxies etc. yield none)
        ip = str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        ip = None
    return ActorContext(actor_type, user_id, ref, getattr(request.state, "request_id", None), ip)


def get_caller(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
               db: Session = Depends(get_db)) -> Caller:
    verifier = request.app.state.tokens
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthenticated("Authentication required")
    if verifier is None:
        raise NotConfigured("Authentication is not configured")
    try:
        claims = verifier.verify(creds.credentials)
    except InvalidToken:
        raise Unauthenticated("Invalid or expired token") from None
    subject = str(claims["sub"])
    if subject in get_settings().service_subjects:
        return Caller(Principal("service", subject), None, _ctx(request, ActorType.SERVICE, ref=subject))
    user = db.scalar(select(User).where(User.external_identity_id == subject))
    if user is None or user.status != "ACTIVE":
        # Identical response for "unknown" and "disabled" so identities cannot be enumerated.
        audit.record_independent(_ctx(request, ActorType.USER, user.id if user else None, subject), "auth.login_denied",
                                 outcome=AuditOutcome.DENIED, details={"reason": "unknown_or_inactive"})
        raise Forbidden("Access denied")
    return Caller(Principal("user", subject, user.id, user.username), user, _ctx(request, ActorType.USER, user.id, subject))


def require_user(caller: Caller = Depends(get_caller)) -> Caller:
    if caller.principal.is_service:
        raise Forbidden("Not available to service identities")
    return caller


def require_permission(code: str):
    def dependency(caller: Caller = Depends(require_user), db: Session = Depends(get_db)) -> Caller:
        if not authorization_service.has_permission(db, caller.user, code):
            audit.record_independent(caller.ctx, "authz.denied", target_type="permission", target_id=code,
                                     outcome=AuditOutcome.DENIED)
            raise Forbidden("Insufficient permissions")
        return caller

    return dependency
