"""Role -> permission mapping (additive: re-seeding never removes grants an administrator approved)."""
_AGENT = ["case.read_assigned", "case.update", "case.escalate", "ptp.create", "ptp.read", "ptp.update",
          "communication.read", "communication.create"]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "COLLECTION_AGENT": _AGENT,
    "COLLECTION_SUPERVISOR": _AGENT + ["case.read_team", "case.assign", "case.create", "report.view_team",
                                        "iam.team.read", "iam.access.request"],
    "COLLECTION_MANAGER": ["case.read_team", "case.read_portfolio", "case.assign", "report.view_team",
                           "report.view_portfolio", "ptp.read", "communication.read", "policy.read", "iam.team.read",
                           "iam.access.request"],
    "POLICY_ADMINISTRATOR": ["policy.read", "policy.create", "policy.update_draft", "policy.delete_draft",
                             "policy.simulate", "policy.submit", "policy.view_audit"],
    "POLICY_APPROVER": ["policy.read", "policy.approve", "policy.reject", "policy.activate", "policy.view_audit"],
    "SYSTEM_ADMINISTRATOR": [
        "iam.user.read", "iam.user.create", "iam.user.update", "iam.user.deactivate",
        "iam.role.read", "iam.role.create", "iam.role.update", "iam.permission.read", "iam.permission.assign",
        "iam.user_role.assign", "iam.user_role.revoke", "iam.team.read", "iam.team.manage",
        "iam.scope.read", "iam.scope.assign", "iam.access.request", "iam.access.approve", "iam.audit.read"],
    "RECOVERY_LEGAL_OFFICER": ["recovery.read", "recovery.review", "case.read_assigned", "ptp.read", "communication.read"],
    "HARDSHIP_OFFICER": ["case.read_assigned", "case.update", "ptp.read", "ptp.update", "communication.read",
                         "communication.create"],
    "COMPLIANCE_AUDITOR": ["iam.audit.read", "iam.user.read", "iam.role.read", "iam.permission.read", "iam.team.read",
                           "iam.scope.read", "policy.read", "policy.view_audit", "report.view_portfolio",
                           "case.read_portfolio", "recovery.read", "communication.read"],
    "PORTFOLIO_EXECUTIVE": ["report.view_portfolio", "policy.read"],
}
