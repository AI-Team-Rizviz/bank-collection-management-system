from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.common import ORMModel


class PermissionOut(ORMModel):
    id: uuid.UUID
    code: str
    description: str
    category: str
    is_sensitive: bool
    allowed_scope_types: list[str] | None


class RolePermissionAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permission_id: uuid.UUID
