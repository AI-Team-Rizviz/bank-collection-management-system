from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import ORMModel

TeamCode = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,63}$")]
Ref = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,63}$")]


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "code": "TEAM-001", "name": "Karachi Early Bucket", "branch_id": "BR-001", "region_id": "REG-SOUTH"}})
    code: TeamCode
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    branch_id: Ref | None = None
    region_id: Ref | None = None


class TeamPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    branch_id: Ref | None = None
    region_id: Ref | None = None
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class TeamOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    branch_id: str | None
    region_id: str | None
    status: str
    created_at: datetime


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    member_role: Literal["LEAD", "MEMBER"] = "MEMBER"


class MemberOut(ORMModel):
    id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    member_role: str
    status: str
    joined_at: datetime
