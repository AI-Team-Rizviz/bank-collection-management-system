"""Initial permission catalog. Codes are stable identifiers: never rename, only add.

(code, description, category, is_sensitive, allowed_scope_types)
allowed_scope_types=None  -> not resource-scoped.  Otherwise the scope types able to satisfy the permission.
"""
OWN, TEAM, BRANCH, REGION, PORTFOLIO, GLOBAL = "OWN", "TEAM", "BRANCH", "REGION", "PORTFOLIO", "GLOBAL"

PERMISSIONS: list[tuple[str, str, str, bool, list[str] | None]] = [
    # --- policy -----------------------------------------------------------------------------------------------
    ("policy.read", "View collection policies and versions", "policy", False, None),
    ("policy.create", "Create a collection policy draft", "policy", False, None),
    ("policy.update_draft", "Modify a draft policy / its rules", "policy", False, None),
    ("policy.delete_draft", "Delete a draft policy", "policy", False, None),
    ("policy.simulate", "Validate and simulate policy rules", "policy", False, None),
    ("policy.submit", "Submit a policy for approval", "policy", False, None),
    ("policy.approve", "Approve a submitted policy (never one's own)", "policy", True, None),
    ("policy.reject", "Reject a submitted policy", "policy", False, None),
    ("policy.activate", "Activate an approved policy", "policy", True, None),
    ("policy.view_audit", "View policy approval history and audit trail", "policy", False, None),
    # --- IAM --------------------------------------------------------------------------------------------------
    ("iam.user.read", "View user accounts", "iam", False, None),
    ("iam.user.create", "Create user accounts", "iam", False, None),
    ("iam.user.update", "Update user account details", "iam", False, None),
    ("iam.user.deactivate", "Deactivate / reactivate user accounts", "iam", False, None),
    ("iam.role.read", "View roles and user-role assignments", "iam", False, None),
    ("iam.role.create", "Create custom roles", "iam", True, None),
    ("iam.role.update", "Update roles", "iam", True, None),
    ("iam.permission.read", "View the permission catalog and role mappings", "iam", False, None),
    ("iam.permission.assign", "Map permissions to roles", "iam", True, None),
    ("iam.user_role.assign", "Assign roles to users", "iam", True, None),
    ("iam.user_role.revoke", "Revoke roles from users", "iam", True, None),
    ("iam.team.read", "View teams and memberships", "iam", False, None),
    ("iam.team.manage", "Create teams and manage membership", "iam", False, None),
    ("iam.scope.read", "View access scopes and user scope grants", "iam", False, None),
    ("iam.scope.assign", "Define scopes and grant them to users", "iam", True, None),
    ("iam.access.request", "Raise an access change request (maker)", "iam", False, None),
    ("iam.access.approve", "Approve / reject access change requests (checker)", "iam", True, None),
    ("iam.audit.read", "Read IAM audit records", "iam", True, None),
    # --- collections ------------------------------------------------------------------------------------------
    ("case.read_assigned", "Read collection cases assigned to oneself", "case", False, [OWN]),
    ("case.read_team", "Read collection cases of one's team", "case", False, [TEAM]),
    ("case.read_portfolio", "Read cases across a portfolio / branch / region", "case", False, [PORTFOLIO, BRANCH, REGION, GLOBAL]),
    ("case.create", "Create collection cases", "case", False, [OWN, TEAM]),
    ("case.update", "Update collection case tasks", "case", False, [OWN, TEAM]),
    ("case.assign", "Assign / reassign cases", "case", False, [TEAM, BRANCH, REGION]),
    ("case.escalate", "Escalate a case", "case", False, [OWN, TEAM]),
    ("ptp.create", "Record a Promise to Pay", "ptp", False, [OWN, TEAM]),
    ("ptp.read", "Read Promise to Pay records", "ptp", False, [OWN, TEAM, PORTFOLIO]),
    ("ptp.update", "Update a Promise to Pay", "ptp", False, [OWN, TEAM]),
    ("communication.read", "Read customer communications", "communication", False, [OWN, TEAM, PORTFOLIO]),
    ("communication.create", "Record / send customer communications", "communication", False, [OWN, TEAM]),
    ("report.view_team", "View team performance reports", "report", False, [TEAM]),
    ("report.view_portfolio", "View portfolio-level dashboards and reports", "report", False, [PORTFOLIO, REGION, GLOBAL]),
    ("recovery.read", "Read recovery / legal case information", "recovery", False, [OWN, PORTFOLIO, REGION, GLOBAL]),
    ("recovery.review", "Review recovery / legal actions", "recovery", True, [OWN, PORTFOLIO, REGION, GLOBAL]),
]
