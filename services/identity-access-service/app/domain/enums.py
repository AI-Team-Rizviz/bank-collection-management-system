from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RoleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TeamStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class MemberRole(StrEnum):
    LEAD = "LEAD"
    MEMBER = "MEMBER"


class ScopeType(StrEnum):
    OWN = "OWN"
    TEAM = "TEAM"
    BRANCH = "BRANCH"
    REGION = "REGION"
    PORTFOLIO = "PORTFOLIO"
    GLOBAL = "GLOBAL"


# Scope types whose grant widens data reach beyond a single team and therefore needs maker-checker.
ESCALATING_SCOPE_TYPES = frozenset({ScopeType.REGION, ScopeType.PORTFOLIO, ScopeType.GLOBAL})

# Resource-context attribute that a scope type is matched against (see README "Authorization contract").
SCOPE_RESOURCE_ATTRIBUTE = {
    ScopeType.OWN: "assigned_user_id",
    ScopeType.TEAM: "assigned_team_id",
    ScopeType.BRANCH: "branch_id",
    ScopeType.REGION: "region_id",
    ScopeType.PORTFOLIO: "portfolio_id",
}


class RequestType(StrEnum):
    ASSIGN_ROLE = "ASSIGN_ROLE"
    GRANT_SCOPE = "GRANT_SCOPE"
    GRANT_ROLE_PERMISSION = "GRANT_ROLE_PERMISSION"
    REVOKE_ROLE_PERMISSION = "REVOKE_ROLE_PERMISSION"


class RequestStatus(StrEnum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    FAILURE = "FAILURE"


class ActorType(StrEnum):
    USER = "USER"
    SERVICE = "SERVICE"
    SYSTEM = "SYSTEM"
    ANONYMOUS = "ANONYMOUS"
