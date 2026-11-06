from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.common import ORMModel

Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")]
# Plain pattern rather than EmailStr: reserved domains such as example.invalid are intentionally used for fixtures.
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Display = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _email(v: str) -> str:
    return v.strip().lower()


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "external_identity_id": "oidc-subject-123", "username": "agent001",
        "display_name": "Example Agent", "email": "agent001@example.invalid"}})
    external_identity_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    username: Username
    display_name: Display
    email: Email

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return _email(v)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: Display | None = None
    email: Email | None = None

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return _email(v) if v else v

    @field_validator("display_name", "email")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v


class UserOut(ORMModel):
    id: uuid.UUID
    external_identity_id: str
    username: str
    display_name: str
    email: str
    status: str
    authz_version: int
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None


class UserRoleAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: uuid.UUID
    valid_until: datetime | None = Field(None, description="Optional expiry (timezone-aware, must be in the future)")

    @field_validator("valid_until")
    @classmethod
    def _tz(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("valid_until must be timezone-aware")
        return v
