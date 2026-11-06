"""DEVELOPMENT-ONLY fictional users. Reserved `.invalid` e-mail domain; all share the development password
set by the seeder (DEMO_USER_PASSWORD, default in runner.py). Never seed these outside development/test.
"""
# (username, display_name, roles, [(team_code, member_role)], [(scope_type, scope_value)])
DEMO_USERS = [
    ("agent001", "Demo Agent One", ["COLLECTION_AGENT"], [("TEAM-001", "MEMBER")], [("OWN", None)]),
    ("agent002", "Demo Agent Two", ["COLLECTION_AGENT"], [("TEAM-001", "MEMBER")], [("OWN", None)]),
    ("agent003", "Demo Agent Three", ["COLLECTION_AGENT"], [("TEAM-002", "MEMBER")], [("OWN", None)]),
    ("supervisor001", "Demo Supervisor One", ["COLLECTION_SUPERVISOR"], [("TEAM-001", "LEAD")], [("TEAM", "TEAM-001")]),
    ("supervisor002", "Demo Supervisor Two", ["COLLECTION_SUPERVISOR"], [("TEAM-002", "LEAD")], [("TEAM", "TEAM-002")]),
    ("manager001", "Demo Manager", ["COLLECTION_MANAGER"], [],
     [("TEAM", "TEAM-001"), ("TEAM", "TEAM-002"), ("PORTFOLIO", "PF-PERSONAL-LOAN"), ("PORTFOLIO", "PF-CARDS")]),
    ("policyadmin001", "Demo Policy Administrator", ["POLICY_ADMINISTRATOR"], [], []),
    ("policyapprover001", "Demo Policy Approver", ["POLICY_APPROVER"], [], []),
    ("sysadmin001", "Demo System Administrator One", ["SYSTEM_ADMINISTRATOR"], [], []),
    ("sysadmin002", "Demo System Administrator Two", ["SYSTEM_ADMINISTRATOR"], [], []),
    ("legal001", "Demo Legal Officer", ["RECOVERY_LEGAL_OFFICER"], [], [("OWN", None)]),
    ("hardship001", "Demo Hardship Officer", ["HARDSHIP_OFFICER"], [], [("OWN", None)]),
    ("auditor001", "Demo Compliance Auditor", ["COMPLIANCE_AUDITOR"], [], [("GLOBAL", None)]),
    ("exec001", "Demo Business Executive", ["PORTFOLIO_EXECUTIVE"], [], [("GLOBAL", None)]),
]


def external_id(username: str) -> str:
    return f"demo-{username}"


def email(username: str) -> str:
    return f"{username}@example.invalid"
