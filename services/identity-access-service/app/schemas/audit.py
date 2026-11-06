from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    id: int
    occurred_at: datetime
    actor_type: str
    actor_user_id: Any
    actor_ref: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    details: dict[str, Any]
    request_id: str | None
