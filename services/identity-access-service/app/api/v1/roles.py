import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission
from app.application import role_service
from app.core.database import get_db
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.roles import RoleCreate, RoleOut, RolePatch

router = APIRouter(prefix="/roles", tags=["Roles"], responses=ERROR_RESPONSES)


@router.post("", response_model=RoleOut, status_code=201, summary="Create a custom (non-system, non-privileged) role")
def create_role(body: RoleCreate, c: Caller = Depends(require_permission("iam.role.create")), db: Session = Depends(get_db)):
    return role_service.create_role(db, c.ctx, body)


@router.get("", response_model=Page[RoleOut], summary="List roles")
def list_roles(status: str | None = Query(None, pattern="^(ACTIVE|INACTIVE)$"), is_system: bool | None = None,
               page: tuple[int, int] = Depends(pagination), c: Caller = Depends(require_permission("iam.role.read")),
               db: Session = Depends(get_db)):
    items, total = role_service.list_roles(db, status=status, is_system=is_system, limit=page[0], offset=page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])


@router.get("/{role_id}", response_model=RoleOut, summary="Get a role")
def get_role(role_id: uuid.UUID, c: Caller = Depends(require_permission("iam.role.read")), db: Session = Depends(get_db)):
    return role_service.get_role(db, role_id)


@router.patch("/{role_id}", response_model=RoleOut, summary="Update a role (system roles: description only)")
def patch_role(role_id: uuid.UUID, body: RolePatch, c: Caller = Depends(require_permission("iam.role.update")),
               db: Session = Depends(get_db)):
    return role_service.update_role(db, c.ctx, role_id, body)
