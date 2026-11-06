import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission
from app.application import scope_service
from app.core.database import get_db
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.scopes import ScopeCreate, ScopeOut, UserScopeGrant, UserScopeOut

router = APIRouter(tags=["Access Scopes"], responses=ERROR_RESPONSES)


@router.get("/scopes", response_model=Page[ScopeOut], summary="List defined access scopes")
def list_scopes(scope_type: str | None = Query(None, pattern="^(OWN|TEAM|BRANCH|REGION|PORTFOLIO|GLOBAL)$"),
                page: tuple[int, int] = Depends(pagination), c: Caller = Depends(require_permission("iam.scope.read")),
                db: Session = Depends(get_db)):
    items, total = scope_service.list_scopes(db, scope_type=scope_type, limit=page[0], offset=page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])


@router.post("/scopes", response_model=ScopeOut, status_code=201, summary="Define a new access scope")
def create_scope(body: ScopeCreate, c: Caller = Depends(require_permission("iam.scope.assign")), db: Session = Depends(get_db)):
    return scope_service.create_scope(db, c.ctx, body)


@router.get("/users/{user_id}/scopes", response_model=list[UserScopeOut], summary="A user's active scopes")
def user_scopes(user_id: uuid.UUID, c: Caller = Depends(require_permission("iam.scope.read")), db: Session = Depends(get_db)):
    return scope_service.list_user_scopes(db, user_id)


@router.post("/users/{user_id}/scopes", response_model=UserScopeOut, status_code=201,
             summary="Grant a scope (REGION/PORTFOLIO/GLOBAL need an access request)")
def grant_scope(user_id: uuid.UUID, body: UserScopeGrant, c: Caller = Depends(require_permission("iam.scope.assign")),
                db: Session = Depends(get_db)):
    return scope_service.grant_scope(db, c.ctx, user_id, body.scope_id, valid_until=body.valid_until)


@router.delete("/users/{user_id}/scopes/{scope_id}", status_code=204, summary="Revoke a scope")
def revoke_scope(user_id: uuid.UUID, scope_id: uuid.UUID, c: Caller = Depends(require_permission("iam.scope.assign")),
                 db: Session = Depends(get_db)):
    scope_service.revoke_scope(db, c.ctx, user_id, scope_id)
    return Response(status_code=204)
