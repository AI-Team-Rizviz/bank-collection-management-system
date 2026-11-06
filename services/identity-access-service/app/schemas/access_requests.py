from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.domain.enums import RequestType
from app.schemas.common import ORMModel


class AccessRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "request_type": "ASSIGN_ROLE", "target_user_id": "00000000-0000-0000-0000-000000000001",
        "role_id": "00000000-0000-0000-0000-000000000002", "justification": "Covering for team lead (approved by HR)"}})
    request_type: RequestType
    target_user_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    permission_id: uuid.UUID | None = None
    scope_id: uuid.UUID | None = None
    valid_until: datetime | None = None
    justification: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]

    @model_validator(mode="after")
    def _shape(self):
        t = self.request_type
        need = {
            RequestType.ASSIGN_ROLE: {"target_user_id", "role_id"},
            RequestType.GRANT_SCOPE: {"target_user_id", "scope_id"},
            RequestType.GRANT_ROLE_PERMISSION: {"role_id", "permission_id"},
            RequestType.REVOKE_ROLE_PERMISSION: {"role_id", "permission_id"},
        }[t]
        given = {f for f in ("target_user_id", "role_id", "permission_id", "scope_id") if getattr(self, f) is not None}
        if given != need:
            raise ValueError(f"{t.value} requires exactly: {', '.join(sorted(need))}")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None:
                raise ValueError("valid_until must be timezone-aware")
            if t not in (RequestType.ASSIGN_ROLE, RequestType.GRANT_SCOPE):
                raise ValueError("valid_until only applies to ASSIGN_ROLE and GRANT_SCOPE")
        return self


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ApprovalOut(ORMModel):
    approver_id: uuid.UUID
    decision: str
    comment: str | None
    decided_at: datetime


class AccessRequestOut(ORMModel):
    id: uuid.UUID
    request_type: str
    status: str
    requested_by: uuid.UUID
    target_user_id: uuid.UUID | None
    role_id: uuid.UUID | None
    permission_id: uuid.UUID | None
    scope_id: uuid.UUID | None
    valid_until: datetime | None
    justification: str
    decided_at: datetime | None
    applied_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    approvals: list[ApprovalOut] = []
