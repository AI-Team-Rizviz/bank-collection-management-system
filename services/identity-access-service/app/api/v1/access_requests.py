import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission, require_user
from app.application import access_service, authorization_service
from app.core.database import get_db
from app.core.exceptions import Forbidden
from app.schemas.access_requests import AccessRequestCreate, AccessRequestOut, Decision
from app.schemas.common import ERROR_RESPONSES, Page

router = APIRouter(prefix="/access-requests", tags=["Access Requests"], responses=ERROR_RESPONSES)


@router.post("", response_model=AccessRequestOut, status_code=201, summary="Request an access change (maker)")
def create(body: AccessRequestCreate, c: Caller = Depends(require_permission("iam.access.request")),
           db: Session = Depends(get_db)):
    return access_service.create_request(db, c.ctx, body)


@router.get("", response_model=Page[AccessRequestOut],
            summary="List access requests (approvers see all; requesters see their own)")
def list_requests(status: str | None = Query(None, pattern="^(PENDING|APPLIED|REJECTED|FAILED)$"),
                  request_type: str | None = Query(None, max_length=32), page: tuple[int, int] = Depends(pagination),
                  c: Caller = Depends(require_user), db: Session = Depends(get_db)):
    can_approve = authorization_service.has_permission(db, c.user, "iam.access.approve")
    if not can_approve and not authorization_service.has_permission(db, c.user, "iam.access.request"):
        raise Forbidden("Insufficient permissions")
    items, total = access_service.list_requests(db, status=status, request_type=request_type,
                                                requested_by=None if can_approve else c.user.id,
                                                limit=page[0], offset=page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])


@router.get("/{request_id}", response_model=AccessRequestOut, summary="Get an access request")
def get(request_id: uuid.UUID, c: Caller = Depends(require_user), db: Session = Depends(get_db)):
    req = access_service.get_request(db, request_id)
    if req.requested_by != c.user.id and not authorization_service.has_permission(db, c.user, "iam.access.approve"):
        raise Forbidden("Insufficient permissions")
    return req


@router.post("/{request_id}/approve", response_model=AccessRequestOut,
             summary="Approve and apply a request (checker; never the requester or beneficiary)")
def approve(request_id: uuid.UUID, body: Decision | None = None,
            c: Caller = Depends(require_permission("iam.access.approve")), db: Session = Depends(get_db)):
    return access_service.approve(db, c.ctx, request_id, body.comment if body else None)


@router.post("/{request_id}/reject", response_model=AccessRequestOut, summary="Reject a request (no privilege changes)")
def reject(request_id: uuid.UUID, body: Decision | None = None,
           c: Caller = Depends(require_permission("iam.access.approve")), db: Session = Depends(get_db)):
    return access_service.reject(db, c.ctx, request_id, body.comment if body else None)
