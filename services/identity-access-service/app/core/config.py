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

    # Login-form authentication: this service verifies passwords and signs its own access tokens.
    jwt_secret_key: str | None = None
    access_token_ttl_seconds: int = Field(3600, ge=60, le=86400)
    token_leeway_seconds: int = Field(30, ge=0, le=120)
    service_subjects: Annotated[list[str], NoDecode] = []

    cors_allowed_origins: Annotated[list[str], NoDecode] = []
    enable_api_docs: bool | None = None
    authz_cache_ttl_seconds: int = Field(60, ge=0, le=3600)

    @field_validator("service_subjects", "cors_allowed_origins", mode="before")
    @classmethod
    def _split(cls, v):
        return _csv(v)

    @field_validator("jwt_secret_key", "migration_database_url", "enable_api_docs", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("database_schema")
    @classmethod
    def _schema_ident(cls, v: str) -> str:
        if not _IDENT.match(v):  # interpolated into DDL, so strictly an identifier
            raise ValueError("DATABASE_SCHEMA must be a simple lower-case identifier")
        return v

    @model_validator(mode="after")
    def _production_rules(self) -> Settings:
        if self.app_env == "production":
            if not self.jwt_secret_key or len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY (at least 32 characters) is required in production")
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
