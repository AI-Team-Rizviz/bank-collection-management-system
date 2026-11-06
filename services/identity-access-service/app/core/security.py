"""Authenticated caller model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Principal:
    kind: Literal["user", "service"]
    subject: str
    user_id: uuid.UUID | None = None
    username: str | None = None

    @property
    def is_service(self) -> bool:
        return self.kind == "service"
