"""IAM-owned tables. No foreign keys leave the `iam` schema; other services reference IAM ids by value only."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base, Timestamps, fk, new_uuid

_UUID = UUID(as_uuid=True)
_TS = DateTime(timezone=True)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(_UUID, primary_key=True, default=new_uuid, server_default=text("gen_random_uuid()"))


class User(Base, Timestamps):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    external_identity_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # salted scrypt; NULL = cannot log in
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    # Bumped on any change that affects the user's effective access; lets consumers detect stale caches.
    authz_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    deactivated_at: Mapped[datetime | None] = mapped_column(_TS)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey(fk("users.id")))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey(fk("users.id")))
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'", name="username_format"),
        CheckConstraint("email = lower(email) AND position('@' in email) > 1", name="email_format"),
        Index("ix_users_status", "status"),
    )


class Role(Base, Timestamps):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Privileged roles can only be assigned through maker-checker.
    is_privileged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    phase: Mapped[str] = mapped_column(String(8), nullable=False, default="MVP", server_default="MVP")
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("phase IN ('MVP','FUTURE')", name="phase"),
        CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{2,63}$'", name="code_format"),
        CheckConstraint("NOT (is_privileged AND NOT is_system)", name="privileged_implies_system"),
    )


class Permission(Base, Timestamps):
    """Seed-managed catalog. The API deliberately offers no way to create permissions."""

    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # NULL = not resource-scoped (e.g. iam.*). Otherwise the scope types able to satisfy it.
    allowed_scope_types: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)))
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'", name="code_format"),
        CheckConstraint(
            "allowed_scope_types IS NULL OR allowed_scope_types <@ "
            "ARRAY['OWN','TEAM','BRANCH','REGION','PORTFOLIO','GLOBAL']::varchar[]",
            name="scope_types",
        ),
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("roles.id"), ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey(fk("permissions.id"), ondelete="CASCADE"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    source_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_role_permissions_permission_id", "permission_id"),)


class RoleConflict(Base):
    """Separation-of-duties: a user may not hold both roles at once."""

    __tablename__ = "role_conflicts"
    role_a_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("roles.id"), ondelete="CASCADE"), primary_key=True)
    role_b_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("roles.id"), ondelete="CASCADE"), primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("role_a_id < role_b_id", name="ordered_pair"),)


class UserRole(Base):
    __tablename__ = "user_roles"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("users.id")), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("roles.id")), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    valid_from: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(_TS)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    source_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    role: Mapped[Role] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','REVOKED')", name="status"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity_window"),
        Index("uq_user_roles_active", "user_id", "role_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_user_roles_user_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
    )


class Team(Base, Timestamps):
    __tablename__ = "teams"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    branch_id: Mapped[str | None] = mapped_column(String(64))
    region_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{1,63}$'", name="code_format"),
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[uuid.UUID] = _pk()
    team_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("teams.id")), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("users.id")), nullable=False)
    member_role: Mapped[str] = mapped_column(String(16), nullable=False, default="MEMBER", server_default="MEMBER")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    added_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    joined_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(_TS)
    __table_args__ = (
        CheckConstraint("member_role IN ('LEAD','MEMBER')", name="member_role"),
        CheckConstraint("status IN ('ACTIVE','REMOVED')", name="status"),
        Index("uq_team_members_active", "team_id", "user_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_team_members_user_id", "user_id"),
    )


class AccessScope(Base, Timestamps):
    __tablename__ = "access_scopes"
    id: Mapped[uuid.UUID] = _pk()
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_value: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    __table_args__ = (
        CheckConstraint("scope_type IN ('OWN','TEAM','BRANCH','REGION','PORTFOLIO','GLOBAL')", name="scope_type"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint(
            "(scope_type IN ('OWN','GLOBAL') AND scope_value IS NULL) OR "
            "(scope_type NOT IN ('OWN','GLOBAL') AND scope_value IS NOT NULL AND scope_value ~ '^[A-Z0-9][A-Z0-9_-]{1,63}$')",
            name="value_matches_type",
        ),
        Index("uq_access_scopes_type_value", "scope_type", text("coalesce(scope_value, '')"), unique=True),
    )


class UserAccessScope(Base):
    __tablename__ = "user_access_scopes"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("users.id")), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("access_scopes.id")), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    valid_from: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(_TS)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    source_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    scope: Mapped[AccessScope] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','REVOKED')", name="status"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity_window"),
        Index("uq_user_access_scopes_active", "user_id", "scope_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_user_access_scopes_user_id", "user_id"),
    )


class AccessRequest(Base, Timestamps):
    __tablename__ = "access_requests"
    id: Mapped[uuid.UUID] = _pk()
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    requested_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("users.id")), nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey(fk("users.id")))
    role_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey(fk("roles.id")))
    permission_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey(fk("permissions.id")))
    scope_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey(fk("access_scopes.id")))
    valid_until: Mapped[datetime | None] = mapped_column(_TS)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(_TS)
    applied_at: Mapped[datetime | None] = mapped_column(_TS)
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    approvals: Mapped[list[AccessApproval]] = relationship(back_populates="request", lazy="selectin")
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','APPLIED','REJECTED','FAILED')", name="status"),
        CheckConstraint(
            "(request_type = 'ASSIGN_ROLE' AND target_user_id IS NOT NULL AND role_id IS NOT NULL "
            "  AND permission_id IS NULL AND scope_id IS NULL) OR "
            "(request_type = 'GRANT_SCOPE' AND target_user_id IS NOT NULL AND scope_id IS NOT NULL "
            "  AND role_id IS NULL AND permission_id IS NULL) OR "
            "(request_type IN ('GRANT_ROLE_PERMISSION','REVOKE_ROLE_PERMISSION') AND role_id IS NOT NULL "
            "  AND permission_id IS NOT NULL AND target_user_id IS NULL AND scope_id IS NULL)",
            name="shape_matches_type",
        ),
        Index("ix_access_requests_status", "status"),
        Index("ix_access_requests_requested_by", "requested_by"),
    )


class AccessApproval(Base):
    __tablename__ = "access_approvals"
    id: Mapped[uuid.UUID] = _pk()
    request_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("access_requests.id")), nullable=False)
    approver_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey(fk("users.id")), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    request: Mapped[AccessRequest] = relationship(back_populates="approvals")
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVED','REJECTED')", name="decision"),
        UniqueConstraint("request_id", "approver_id", name="uq_access_approvals_request_approver"),
        Index("ix_access_approvals_approver_id", "approver_id"),
    )


class AuditLog(Base):
    """Append-only (enforced by trigger + restricted grants). Intentionally no FKs so history outlives entities."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(_TS, server_default=func.now(), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    actor_ref: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(48))
    target_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(INET)
    __table_args__ = (
        CheckConstraint("outcome IN ('SUCCESS','DENIED','FAILURE')", name="outcome"),
        CheckConstraint("actor_type IN ('USER','SERVICE','SYSTEM','ANONYMOUS')", name="actor_type"),
        Index("ix_audit_logs_occurred_at", "occurred_at"),
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
        Index("ix_audit_logs_action", "action"),
    )
