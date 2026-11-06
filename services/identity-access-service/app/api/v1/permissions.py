import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission
from app.application import permission_service
from app.core.database import get_db
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.permissions import PermissionOut, RolePermissionAdd

router = APIRouter(tags=["Permissions"], responses=ERROR_RESPONSES)


@router.get("/permissions", response_model=Page[PermissionOut], summary="List the (read-only) permission catalog")
def list_permissions(category: str | None = Query(None, max_length=32), is_sensitive: bool | None = None,
                     q: str | None = Query(None, max_length=64), page: tuple[int, int] = Depends(pagination),
                     c: Caller = Depends(require_permission("iam.permission.read")), db: Session = Depends(get_db)):
    items, total = permission_service.list_permissions(db, category=category, is_sensitive=is_sensitive, q=q,
                                                       limit=page[0], offset=page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionOut], summary="Permissions mapped to a role")
def role_permissions(role_id: uuid.UUID, c: Caller = Depends(require_permission("iam.permission.read")),
                     db: Session = Depends(get_db)):
    return permission_service.list_role_permissions(db, role_id)


@router.post("/roles/{role_id}/permissions", response_model=PermissionOut, status_code=201,
             summary="Map a permission to a custom role (sensitive permissions / system roles need an access request)")
def add_role_permission(role_id: uuid.UUID, body: RolePermissionAdd,
                        c: Caller = Depends(require_permission("iam.permission.assign")), db: Session = Depends(get_db)):
    return permission_service.grant_role_permission(db, c.ctx, role_id, body.permission_id)


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204, summary="Remove a permission from a role")
def remove_role_permission(role_id: uuid.UUID, permission_id: uuid.UUID,
                           c: Caller = Depends(require_permission("iam.permission.assign")), db: Session = Depends(get_db)):
    permission_service.revoke_role_permission(db, c.ctx, role_id, permission_id)
    return Response(status_code=204)
