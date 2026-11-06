import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission
from app.application import role_service, user_service
from app.core.database import get_db
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.roles import UserRoleOut
from app.schemas.users import UserCreate, UserOut, UserRoleAssign, UserUpdate

router = APIRouter(responses=ERROR_RESPONSES)


@router.post("/users", response_model=UserOut, status_code=201, tags=["Users"], summary="Create a user")
def create_user(body: UserCreate, c: Caller = Depends(require_permission("iam.user.create")), db: Session = Depends(get_db)):
    return user_service.create_user(db, c.ctx, body)


@router.get("/users", response_model=Page[UserOut], tags=["Users"], summary="List users")
def list_users(status: str | None = Query(None, pattern="^(ACTIVE|INACTIVE)$"), q: str | None = Query(None, max_length=64),
               page: tuple[int, int] = Depends(pagination), c: Caller = Depends(require_permission("iam.user.read")),
               db: Session = Depends(get_db)):
    items, total = user_service.list_users(db, status=status, q=q, limit=page[0], offset=page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])


@router.get("/users/{user_id}", response_model=UserOut, tags=["Users"], summary="Get a user")
def get_user(user_id: uuid.UUID, c: Caller = Depends(require_permission("iam.user.read")), db: Session = Depends(get_db)):
    return user_service.get_user(db, user_id)


@router.patch("/users/{user_id}", response_model=UserOut, tags=["Users"], summary="Update display name / email")
def update_user(user_id: uuid.UUID, body: UserUpdate, c: Caller = Depends(require_permission("iam.user.update")),
                db: Session = Depends(get_db)):
    return user_service.update_user(db, c.ctx, user_id, body)


@router.post("/users/{user_id}/deactivate", response_model=UserOut, tags=["Users"], summary="Deactivate a user")
def deactivate(user_id: uuid.UUID, c: Caller = Depends(require_permission("iam.user.deactivate")), db: Session = Depends(get_db)):
    return user_service.deactivate_user(db, c.ctx, user_id)


@router.post("/users/{user_id}/reactivate", response_model=UserOut, tags=["Users"], summary="Reactivate a user")
def reactivate(user_id: uuid.UUID, c: Caller = Depends(require_permission("iam.user.deactivate")), db: Session = Depends(get_db)):
    return user_service.reactivate_user(db, c.ctx, user_id)


@router.get("/users/{user_id}/roles", response_model=list[UserRoleOut], tags=["Roles"], summary="List a user's active roles")
def list_user_roles(user_id: uuid.UUID, c: Caller = Depends(require_permission("iam.role.read")), db: Session = Depends(get_db)):
    return role_service.list_user_roles(db, user_id)


@router.post("/users/{user_id}/roles", response_model=UserRoleOut, status_code=201, tags=["Roles"],
             summary="Assign a role (non-privileged roles only; privileged roles need an access request)")
def assign_role(user_id: uuid.UUID, body: UserRoleAssign, c: Caller = Depends(require_permission("iam.user_role.assign")),
                db: Session = Depends(get_db)):
    return role_service.assign_role(db, c.ctx, user_id, body.role_id, valid_until=body.valid_until)


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204, tags=["Roles"], summary="Revoke a role")
def revoke_role(user_id: uuid.UUID, role_id: uuid.UUID, c: Caller = Depends(require_permission("iam.user_role.revoke")),
                db: Session = Depends(get_db)):
    role_service.revoke_role(db, c.ctx, user_id, role_id)
    return Response(status_code=204)
