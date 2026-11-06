from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.domain.enums import ScopeType
from app.schemas.common import ORMModel


class ScopeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "scope_type": "BRANCH", "scope_value": "BR-001", "name": "Branch BR-001"}})
    scope_type: ScopeType
    scope_value: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,63}$")] | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]

    @model_validator(mode="after")
    def _shape(self):
        if self.scope_type in (ScopeType.OWN, ScopeType.GLOBAL):
            if self.scope_value is not None:
                raise ValueError(f"{self.scope_type} scopes must not have a scope_value")
        elif self.scope_value is None:
            raise ValueError(f"{self.scope_type} scopes require a scope_value")
        return self


class ScopeOut(ORMModel):
    id: uuid.UUID
    scope_type: str
    scope_value: str | None
    name: str
    status: str


class UserScopeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: uuid.UUID
    valid_until: datetime | None = Field(None, description="Optional expiry (timezone-aware, future)")

    @field_validator("valid_until")
    @classmethod
    def _tz(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("valid_until must be timezone-aware")
        return v


class UserScopeOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    scope: ScopeOut
    status: str
    valid_from: datetime
    valid_until: datetime | None
    granted_by: uuid.UUID | None
