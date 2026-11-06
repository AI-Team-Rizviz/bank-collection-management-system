from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ScopeRef(BaseModel):
    scope_type: str
    scope_value: str | None


class PermissionInfo(BaseModel):
    code: str
    is_sensitive: bool
    allowed_scope_types: list[str] | None


class MeOut(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    status: str
    roles: list[str]
    scopes: list[ScopeRef]
    authz_version: int


class MyPermissionsOut(BaseModel):
    user_id: uuid.UUID
    authz_version: int
    evaluated_at: datetime
    cache_ttl_seconds: int = Field(description="Non-sensitive grants may be cached this long; sensitive ones never.")
    permissions: list[PermissionInfo]
    scopes: list[ScopeRef]


class AuthorizationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "subject": "local-agent001", "permission": "case.read_team",
        "resource": {"case_id": "CASE-10001", "assigned_team_id": "TEAM-001", "branch_id": "BR-001"}}})
    user_id: uuid.UUID | None = Field(None, description="IAM user id (from a validated token claim mapping)")
    subject: Annotated[str, StringConstraints(max_length=255)] | None = Field(
        None, description="Validated token `sub` of the end user")
    permission: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=100)]
    resource: dict[str, Any] | None = Field(None, description="Trusted attributes fetched from the owning service")

    @model_validator(mode="after")
    def _one_identity(self):
        if self.user_id is not None and self.subject is not None:
            raise ValueError("provide either user_id or subject, not both")
        return self


class AuthorizationDecision(BaseModel):
    allowed: bool
    reason: str
    permission: str
    user_id: uuid.UUID | None
    matched_scope: ScopeRef | None
    authz_version: int | None
    evaluated_at: datetime
    cache_ttl_seconds: int
