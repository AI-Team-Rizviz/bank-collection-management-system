"""Pure authorization rules (no I/O): RBAC + scope evaluation and the maker-checker triggers."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.enums import ESCALATING_SCOPE_TYPES, SCOPE_RESOURCE_ATTRIBUTE, ScopeType


@dataclass(frozen=True)
class PermissionGrant:
    code: str
    is_sensitive: bool
    allowed_scope_types: tuple[str, ...] | None


@dataclass(frozen=True)
class ScopeGrant:
    scope_type: str
    scope_value: str | None


@dataclass(frozen=True)
class AuthzDecision:
    allowed: bool
    reason: str
    matched_scope: ScopeGrant | None = None


def evaluate(
    *,
    user_id: Any,
    permission: str,
    grants: Mapping[str, PermissionGrant],
    scopes: Iterable[ScopeGrant],
    resource: Mapping[str, Any] | None,
) -> AuthzDecision:
    """Deny by default. Allowed only if the permission is granted AND (when it is resource-scoped) one of the
    user's active scopes covers the trusted resource attributes."""
    grant = grants.get(permission)
    if grant is None:
        return AuthzDecision(False, "permission_not_granted")
    if grant.allowed_scope_types is None:
        return AuthzDecision(True, "allowed")
    if not resource:
        return AuthzDecision(False, "resource_context_required")
    for sc in scopes:
        if sc.scope_type not in grant.allowed_scope_types:
            continue
        stype = ScopeType(sc.scope_type)
        if stype is ScopeType.GLOBAL:
            return AuthzDecision(True, "allowed", sc)
        attr = SCOPE_RESOURCE_ATTRIBUTE[stype]
        actual = resource.get(attr)
        if actual is None:
            continue
        expected = str(user_id) if stype is ScopeType.OWN else sc.scope_value
        if str(actual) == expected:
            return AuthzDecision(True, "allowed", sc)
    return AuthzDecision(False, "scope_mismatch")


def scope_needs_approval(scope_type: str) -> bool:
    return ScopeType(scope_type) in ESCALATING_SCOPE_TYPES


def role_needs_approval(*, is_privileged: bool) -> bool:
    return is_privileged


def role_permission_change_needs_approval(*, role_is_system: bool, permission_is_sensitive: bool) -> bool:
    """Any change to a system role, or any grant of a sensitive permission, is maker-checker."""
    return role_is_system or permission_is_sensitive
