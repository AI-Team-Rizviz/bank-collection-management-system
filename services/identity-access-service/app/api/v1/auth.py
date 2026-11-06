"""Username/password login. The only unauthenticated endpoint besides /health."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import NotConfigured, _ctx
from app.core.database import get_db
from app.core.exceptions import Unauthenticated
from app.core.passwords import verify_password
from app.domain.enums import ActorType, AuditOutcome
from app.domain.models import User
from app.infrastructure import audit_repository as audit

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


@router.post("/login", response_model=LoginResponse, summary="Exchange username + password for an access token")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    tokens = request.app.state.tokens
    if tokens is None:
        raise NotConfigured("Authentication is not configured")
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    ok = verify_password(body.password, user.password_hash if user else None)  # always derives: no timing oracle
    if not (ok and user is not None and user.status == "ACTIVE"):
        # One generic answer for unknown user, wrong password, no password set and deactivated account.
        ctx = _ctx(request, ActorType.USER, user.id if user else None, body.username)
        audit.record_independent(ctx, "auth.login_failed", outcome=AuditOutcome.DENIED, details={"reason": "invalid_credentials"})
        raise Unauthenticated("Invalid username or password")
    ctx = _ctx(request, ActorType.USER, user.id, user.external_identity_id)
    audit.record_independent(ctx, "auth.login", outcome=AuditOutcome.SUCCESS)
    return LoginResponse(access_token=tokens.issue(user.external_identity_id), expires_in=tokens.ttl_seconds)
