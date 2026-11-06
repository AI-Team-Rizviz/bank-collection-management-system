"""Fictional teams and access-scope definitions (no real bank branches/regions)."""
TEAMS = [  # (code, name, branch_id, region_id)
    ("TEAM-001", "Karachi Early Bucket (Retail)", "BR-001", "REG-SOUTH"),
    ("TEAM-002", "Lahore Early Bucket (Retail)", "BR-002", "REG-NORTH"),
    ("TEAM-003", "Islamabad Cards Collections", "BR-003", "REG-NORTH"),
]

SCOPES = [  # (type, value, name)  -- TEAM scopes are derived from TEAMS
    ("OWN", None, "Own assigned items"),
    ("GLOBAL", None, "Global (all data)"),
    ("BRANCH", "BR-001", "Branch BR-001"), ("BRANCH", "BR-002", "Branch BR-002"), ("BRANCH", "BR-003", "Branch BR-003"),
    ("REGION", "REG-SOUTH", "Region South"), ("REGION", "REG-NORTH", "Region North"),
    ("PORTFOLIO", "PF-PERSONAL-LOAN", "Personal loans portfolio"),
    ("PORTFOLIO", "PF-CARDS", "Credit cards portfolio"),
    ("PORTFOLIO", "PF-SCOOTY", "Scooty / bike financing portfolio"),
]
