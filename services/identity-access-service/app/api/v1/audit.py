import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission
from app.application.common import paginate
from app.core.database import get_db
from app.infrastructure import audit_repository as audit
from app.schemas.audit import AuditLogOut
from app.schemas.common import ERROR_RESPONSES, Page

router = APIRouter(tags=["Audit"], responses=ERROR_RESPONSES)


@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="Search IAM audit records (newest first)")
def audit_logs(action: str | None = Query(None, max_length=80), actor_user_id: uuid.UUID | None = None,
               target_type: str | None = Query(None, max_length=48), target_id: str | None = Query(None, max_length=64),
               outcome: str | None = Query(None, pattern="^(SUCCESS|DENIED|FAILURE)$"),
               occurred_from: datetime | None = None, occurred_to: datetime | None = None,
               page: tuple[int, int] = Depends(pagination), c: Caller = Depends(require_permission("iam.audit.read")),
               db: Session = Depends(get_db)):
    stmt = audit.query(db, action=action, actor_user_id=actor_user_id, target_type=target_type, target_id=target_id,
                       outcome=outcome, occurred_from=occurred_from, occurred_to=occurred_to)
    stmt = stmt.order_by(audit.AuditLog.occurred_at.desc(), audit.AuditLog.id.desc())
    items, total = paginate(db, stmt, page[0], page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])
