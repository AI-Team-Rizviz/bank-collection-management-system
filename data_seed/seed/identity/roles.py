"""The ten CMS business roles (stable codes) and separation-of-duties conflicts.

NOTE: there is intentionally NO "Integration / Support Engineer" role: it is excluded from the CMS design.
(code, name, description, phase, is_privileged)
"""
ROLES = [
    ("COLLECTION_AGENT", "Collection Agent", "Works assigned collection cases, records interactions and Promises to Pay.", "MVP", False),
    ("COLLECTION_SUPERVISOR", "Collection Supervisor", "Manages team portfolios, assignments and escalations.", "MVP", False),
    ("COLLECTION_MANAGER", "Collection Manager", "Monitors portfolio performance and supervises collection teams.", "MVP", False),
    ("POLICY_ADMINISTRATOR", "Policy Administrator", "Authors, simulates and submits collection policies. Cannot approve.", "MVP", True),
    ("POLICY_APPROVER", "Policy Approver", "Reviews and approves/rejects policy changes.", "MVP", True),
    ("SYSTEM_ADMINISTRATOR", "System Administrator", "Administers CMS users, roles, teams and scopes. No business-data access.", "MVP", True),
    ("RECOVERY_LEGAL_OFFICER", "Recovery / Legal Officer", "Handles recovery and legal escalations.", "FUTURE", False),
    ("HARDSHIP_OFFICER", "Hardship / Restructuring Officer", "Handles hardship and restructuring cases.", "FUTURE", False),
    ("COMPLIANCE_AUDITOR", "Compliance Officer / Auditor", "Independent read-only oversight and audit access.", "FUTURE", True),
    ("PORTFOLIO_EXECUTIVE", "Portfolio / Business Executive", "Executive portfolio dashboards (read-only).", "FUTURE", False),
]

# Pairs that must never be held by the same person (enforced on assignment).
ROLE_CONFLICTS = [
    ("POLICY_ADMINISTRATOR", "POLICY_APPROVER", "Maker-checker for policies: authors must not approve"),
    ("SYSTEM_ADMINISTRATOR", "POLICY_APPROVER", "IAM administration is separate from business approval"),
    ("SYSTEM_ADMINISTRATOR", "POLICY_ADMINISTRATOR", "IAM administration is separate from policy authoring"),
    ("SYSTEM_ADMINISTRATOR", "COLLECTION_AGENT", "Administrators get no collection-data access"),
    ("SYSTEM_ADMINISTRATOR", "COLLECTION_SUPERVISOR", "Administrators get no collection-data access"),
    ("SYSTEM_ADMINISTRATOR", "COLLECTION_MANAGER", "Administrators get no collection-data access"),
    ("SYSTEM_ADMINISTRATOR", "COMPLIANCE_AUDITOR", "Auditor independence"),
]
