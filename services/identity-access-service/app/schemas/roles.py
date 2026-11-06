from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import ORMModel

RoleCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "code": "BRANCH_REVIEWER", "name": "Branch Reviewer", "description": "Custom read-only role"}})
    code: RoleCode
    name: Name
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None


class RolePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class RoleOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    status: str
    is_system: bool
    is_privileged: bool
    phase: str
    created_at: datetime
    updated_at: datetime


class UserRoleOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: RoleOut
    status: str
    valid_from: datetime
    valid_until: datetime | None
    assigned_by: uuid.UUID | None
    source_request_id: uuid.UUID | None
