from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Caller, get_caller, require_user
from app.application import authorization_service as authz
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import BadRequest, Forbidden
from app.domain.enums import AuditOutcome
from app.infrastructure import audit_repository as audit
from app.schemas.authorization import (
    AuthorizationCheck,
    AuthorizationDecision,
    MeOut,
    MyPermissionsOut,
    PermissionInfo,
    ScopeRef,
)
from app.schemas.common import ERROR_RESPONSES

router = APIRouter(tags=["Authorization"], responses=ERROR_RESPONSES)


@router.get("/me", response_model=MeOut, summary="The authenticated caller's identity, roles and scopes")
def me(c: Caller = Depends(require_user), db: Session = Depends(get_db)):
    eff = authz.effective_access(db, c.user)
    return MeOut(user_id=c.user.id, username=c.user.username, display_name=c.user.display_name, status=c.user.status,
                 roles=eff.roles, scopes=[ScopeRef(scope_type=s.scope_type, scope_value=s.scope_value) for s in eff.scopes],
                 authz_version=c.user.authz_version)


@router.get("/me/permissions", response_model=MyPermissionsOut, summary="Effective permissions for the caller")
def my_permissions(c: Caller = Depends(require_user), db: Session = Depends(get_db)):
    eff = authz.effective_access(db, c.user)
    return MyPermissionsOut(
        user_id=c.user.id, authz_version=c.user.authz_version, evaluated_at=authz.utcnow(),
        cache_ttl_seconds=get_settings().authz_cache_ttl_seconds,
        permissions=[PermissionInfo(code=g.code, is_sensitive=g.is_sensitive,
                                    allowed_scope_types=list(g.allowed_scope_types) if g.allowed_scope_types is not None else None)
                     for g in sorted(eff.grants.values(), key=lambda g: g.code)],
        scopes=[ScopeRef(scope_type=s.scope_type, scope_value=s.scope_value) for s in eff.scopes])


@router.post("/authorization/check", response_model=AuthorizationDecision,
             summary="Evaluate one permission (+ resource scope) for a user")
def check(body: AuthorizationCheck, c: Caller = Depends(get_caller), db: Session = Depends(get_db)):
    """Service identities may evaluate any user, with trusted resource attributes from the owning service.
    End users may only evaluate themselves and may not supply resource attributes."""
    if c.principal.is_service:
        if body.user_id is None and body.subject is None:
            raise BadRequest("user_id or subject is required")
        result = authz.check(db, user_id=body.user_id, subject=body.subject, permission=body.permission,
                             resource=body.resource)
    else:
        if body.resource is not None:
            raise Forbidden("Resource-scoped checks require a service identity", code="service_identity_required")
        if (body.user_id and body.user_id != c.user.id) or (body.subject and body.subject != c.user.external_identity_id):
            raise Forbidden("You may only check your own permissions")
        result = authz.check(db, user_id=c.user.id, subject=None, permission=body.permission, resource=None)
    if not result["allowed"]:
        audit.record(db, c.ctx, "authz.check", target_type="permission", target_id=body.permission,
                     outcome=AuditOutcome.DENIED, details={"reason": result["reason"], "subject_user": result["user_id"]})
    sc = result["matched_scope"]
    return AuthorizationDecision(**{**result, "matched_scope": ScopeRef(**sc) if sc else None})
