from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import access_requests, audit, authorization, health, permissions, roles, scopes, teams, users
from app.core.config import Settings, get_settings
from app.core.exceptions import install_handlers
from app.core.logging import configure_logging
from app.infrastructure.identity_provider import TokenVerifier, build_verifier

_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

TAGS = [
    {"name": "Users", "description": "Application user identities (no passwords: authentication is delegated to OIDC)."},
    {"name": "Roles", "description": "Business roles and user-role assignments."},
    {"name": "Permissions", "description": "Read-only permission catalog and role-permission mappings."},
    {"name": "Teams", "description": "Collection teams and memberships."},
    {"name": "Access Scopes", "description": "OWN / TEAM / BRANCH / REGION / PORTFOLIO / GLOBAL data scopes."},
    {"name": "Authorization", "description": "Caller permissions and the service-to-service decision API."},
    {"name": "Access Requests", "description": "Maker-checker workflow for privileged changes."},
    {"name": "Audit", "description": "Append-only security audit trail."},
    {"name": "Health", "description": "Probes."},
]


def create_app(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    docs = settings.docs_enabled

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(
        title="Identity & Access Service",
        version="0.1.0",
        description="IAM for the Bank Collection Management System. All endpoints except /health require a Bearer "
                    "OIDC access token. Default behaviour is DENY.",
        openapi_tags=TAGS,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    app.state.verifier = verifier or build_verifier(settings)
    install_handlers(app)

    if settings.cors_allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_allowed_origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if _RID.match(incoming) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    for r in (users, roles, permissions, teams, scopes, access_requests, authorization, audit, health):
        app.include_router(r.router, prefix="/api/v1")
    return app


def factory() -> FastAPI:
    """uvicorn app.main:factory --factory"""
    return create_app()
