"""Audit persistence. Rows written with `record` commit/roll back with the business transaction;
`record_independent` commits on its own so denials survive the request's rollback."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_sessionmaker
from app.domain.enums import ActorType, AuditOutcome
from app.domain.models import AuditLog

log = logging.getLogger("iam.audit")

_REDACT = ("password", "secret", "token", "authorization")


@dataclass(frozen=True)
class ActorContext:
    actor_type: ActorType
    user_id: uuid.UUID | None = None
    ref: str | None = None
    request_id: str | None = None
    ip: str | None = None

    @classmethod
    def system(cls, ref: str = "cli") -> ActorContext:
        return cls(ActorType.SYSTEM, None, ref)


def _clean(details: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (details or {}).items():
        if any(p in k.lower() for p in _REDACT):
            out[k] = "[REDACTED]"
        else:
            out[k] = v if isinstance(v, int | float | bool | type(None)) else str(v)[:500]
    return out


def _row(ctx: ActorContext, action: str, target_type, target_id, outcome, details) -> AuditLog:
    return AuditLog(
        actor_type=ctx.actor_type.value,
        actor_user_id=ctx.user_id,
        actor_ref=ctx.ref,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        outcome=AuditOutcome(outcome).value,
        details=_clean(details),
        request_id=ctx.request_id,
        ip_address=ctx.ip,
    )


def record(db: Session, ctx: ActorContext, action: str, *, target_type: str | None = None, target_id: Any = None,
           outcome: AuditOutcome = AuditOutcome.SUCCESS, details: dict[str, Any] | None = None) -> None:
    db.add(_row(ctx, action, target_type, target_id, outcome, details))


def record_independent(ctx: ActorContext, action: str, *, target_type: str | None = None, target_id: Any = None,
                       outcome: AuditOutcome = AuditOutcome.DENIED, details: dict[str, Any] | None = None) -> None:
    try:
        with get_sessionmaker()() as s:
            s.add(_row(ctx, action, target_type, target_id, outcome, details))
            s.commit()
    except Exception as exc:  # never let audit plumbing mask the real response, but make the failure visible
        log.error("failed to persist audit record action=%s: %s", action, type(exc).__name__)


def query(db: Session, **f):
    stmt = select(AuditLog)
    for col in ("action", "actor_user_id", "target_type", "target_id", "outcome"):
        if f.get(col) is not None:
            stmt = stmt.where(getattr(AuditLog, col) == f[col])
    if f.get("occurred_from"):
        stmt = stmt.where(AuditLog.occurred_at >= f["occurred_from"])
    if f.get("occurred_to"):
        stmt = stmt.where(AuditLog.occurred_at < f["occurred_to"])
    return stmt
