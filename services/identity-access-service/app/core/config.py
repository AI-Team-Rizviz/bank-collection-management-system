"""Service configuration. Everything comes from the environment / .env; there are no secret defaults."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _csv(v):
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "identity-access-service"
    app_env: str = Field("development", pattern="^(development|test|production)$")
    database_url: str
    migration_database_url: str | None = None
    database_schema: str = "iam"

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: Annotated[list[str], NoDecode] = ["RS256", "ES256"]
    oidc_leeway_seconds: int = Field(30, ge=0, le=120)
    jwks_cache_ttl_seconds: int = Field(300, ge=10)
    service_subjects: Annotated[list[str], NoDecode] = []

    cors_allowed_origins: Annotated[list[str], NoDecode] = []
    enable_api_docs: bool | None = None
    authz_cache_ttl_seconds: int = Field(60, ge=0, le=3600)

    @field_validator("oidc_algorithms", "service_subjects", "cors_allowed_origins", mode="before")
    @classmethod
    def _split(cls, v):
        return _csv(v)

    @field_validator("oidc_issuer", "oidc_audience", "oidc_jwks_url", "migration_database_url", "enable_api_docs", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("database_schema")
    @classmethod
    def _schema_ident(cls, v: str) -> str:
        if not _IDENT.match(v):  # interpolated into DDL, so strictly an identifier
            raise ValueError("DATABASE_SCHEMA must be a simple lower-case identifier")
        return v

    @field_validator("oidc_algorithms")
    @classmethod
    def _asym_only(cls, v: list[str]) -> list[str]:
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
        if not v or any(a not in allowed for a in v):
            raise ValueError("OIDC_ALGORITHMS must be asymmetric algorithms only (no HS*/none)")
        return v

    @model_validator(mode="after")
    def _production_rules(self) -> Settings:
        if self.app_env == "production":
            if not (self.oidc_issuer and self.oidc_audience):
                raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required in production")
            for name in ("oidc_issuer", "oidc_jwks_url"):
                val = getattr(self, name)
                if val and not val.startswith("https://"):
                    raise ValueError(f"{name.upper()} must be https in production")
            if "*" in self.cors_allowed_origins:
                raise ValueError("Wildcard CORS origin is not allowed in production")
        return self

    @property
    def docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return bool(self.enable_api_docs)
        return self.app_env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
