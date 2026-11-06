"""Reference/master data: branches, products, collection teams/agents, synthetic policy rules."""
from __future__ import annotations

import json
import uuid
from datetime import date

from seed.config import GenConfig
from seed.simulation.timeline import rng_for

REF_NS = uuid.uuid5(uuid.NAMESPACE_URL, "bank-cms-seed/reference")

CITIES = [  # (city, province, branch count)
    ("Karachi", "Sindh", 6), ("Lahore", "Punjab", 5), ("Islamabad", "ICT", 3), ("Rawalpindi", "Punjab", 2),
    ("Faisalabad", "Punjab", 2), ("Multan", "Punjab", 2), ("Peshawar", "Khyber Pakhtunkhwa", 2),
    ("Quetta", "Balochistan", 1), ("Hyderabad", "Sindh", 1), ("Sialkot", "Punjab", 1), ("Gujranwala", "Punjab", 1),
    ("Bahawalpur", "Punjab", 1), ("Sukkur", "Sindh", 1), ("Abbottabad", "Khyber Pakhtunkhwa", 1), ("Sargodha", "Punjab", 1),
]
FIRST = ["Ayesha", "Bilal", "Hira", "Usman", "Fatima", "Hamza", "Zainab", "Ali", "Maryam", "Ahmed", "Sana", "Imran",
         "Noor", "Kamran", "Amna", "Faisal", "Saba", "Tariq", "Rabia", "Shahid", "Mehwish", "Asad", "Iqra", "Waqas",
         "Sadia", "Junaid", "Nida", "Rashid", "Farah", "Danish", "Komal", "Adeel", "Bushra", "Salman", "Anum", "Naveed"]
LAST = ["Khan", "Malik", "Sheikh", "Qureshi", "Siddiqui", "Baig", "Chaudhry", "Abbasi", "Raza", "Mirza", "Butt",
        "Ansari", "Memon", "Baloch", "Yousafzai", "Hashmi", "Farooqi", "Javed", "Niazi", "Lodhi"]
TEAMS = [("EARLY", "Early Stage Collections", 1, 30), ("MID", "Mid Stage Collections", 31, 60),
         ("LATE", "Late Stage Collections", 61, 90), ("RECOVERY", "Recovery & Legal", 91, None)]


def branch_list() -> list[dict]:
    out, n = [], 0
    for city, prov, k in CITIES:
        for j in range(k):
            n += 1
            out.append(dict(branch_id=uuid.uuid5(REF_NS, f"branch|{n}"), branch_code=f"SYN-{n:03d}",
                            branch_name=f"Synthetic Branch {city} {j + 1}", city=city, province=prov, is_active=True))
    return out


def reference_rows(cfg: GenConfig) -> dict[str, list[dict]]:
    branches = branch_list()
    pol = cfg.policy
    products = [
        ("PL-SYN", "Synthetic Personal Loan", "PERSONAL_LOAN", dict(
            method="REDUCING_BALANCE", rate_range=pol.loan_rate_range, terms=pol.loan_terms, principal_range=pol.loan_principal_range)),
        ("CC-SYN", "Synthetic Credit Card", "CREDIT_CARD", dict(
            statement_due_days=pol.card_statement_due_days, min_pct=str(pol.card_min_pct), min_floor=str(pol.card_min_floor),
            monthly_finance_rate_pct=str(pol.card_monthly_finance_rate), late_fee=str(pol.card_late_fee))),
        ("AF-SYN", "Synthetic Scooty/Bike Financing", "ASSET_FINANCING", dict(
            method="FLAT_RATE", rate_range=pol.asset_rate_range, terms=pol.asset_terms, down_payment_pct=pol.asset_down_payment_pct)),
    ]
    prod_rows = [dict(product_id=uuid.uuid5(REF_NS, f"product|{code}"), product_code=code, product_name=name,
                      category=cat, currency=cfg.currency, config=json.loads(json.dumps(conf, default=str)), is_synthetic=True)
                 for code, name, cat, conf in products]
    team_rows = [dict(team_id=uuid.uuid5(REF_NS, f"team|{c}"), team_code=c, team_name=n, dpd_from=lo, dpd_to=hi,
                      description="Synthetic team structure for CMS development") for c, n, lo, hi in TEAMS]
    rng = rng_for(cfg.seed, "agents")
    agents = []
    for i in range(1, 25):
        team = team_rows[(i - 1) % 4]
        agents.append(dict(agent_id=uuid.uuid5(REF_NS, f"agent|{i}"), agent_code=f"AGT-{i:03d}",
                           full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", team_id=team["team_id"],
                           branch_id=rng.choice(branches)["branch_id"], is_active=True))
    eff = date(2024, 1, 1)
    v = pol.policy_version
    def rule(code, typ, desc, params, lo=None, hi=None, prod=None):
        return dict(rule_id=uuid.uuid5(REF_NS, f"rule|{code}"), rule_code=code, policy_version=v, rule_type=typ,
                    product_id=uuid.uuid5(REF_NS, f"product|{prod}") if prod else None, dpd_min=lo, dpd_max=hi,
                    parameters=json.loads(json.dumps(params, default=str)), description=f"[SYNTHETIC] {desc}", effective_from=eff)
    rules = [
        rule("DPD_POLICY", "DPD_CALCULATION", "DPD = days since effective due date of oldest unpaid obligation, end-of-day basis",
             dict(grace_days=pol.grace_days, tolerance=pol.tolerance, effective_due="next business day")),
        rule("BUCKET_1_30", "BUCKET", "Bucket DPD 1-30", dict(bucket="DPD_1_30"), 1, 30),
        rule("BUCKET_31_60", "BUCKET", "Bucket DPD 31-60", dict(bucket="DPD_31_60"), 31, 60),
        rule("BUCKET_61_90", "BUCKET", "Bucket DPD 61-90", dict(bucket="DPD_61_90"), 61, 90),
        rule("BUCKET_90_PLUS", "BUCKET", "Bucket DPD 91+", dict(bucket="DPD_90_PLUS"), 91, None),
        rule("COLLECTION_ELIGIBILITY", "ELIGIBILITY", "Account eligible for collections when DPD and overdue amount thresholds are met",
             dict(min_dpd=pol.collection_min_dpd, min_overdue=pol.collection_min_overdue), pol.collection_min_dpd),
        rule("CARD_MIN_PAYMENT", "PAYMENT_OBLIGATION", "Card minimum = max(floor, pct of closing) + unmet earlier minimums",
             dict(pct=pol.card_min_pct, floor=pol.card_min_floor), prod="CC-SYN"),
        rule("CARD_RESTRICTIONS", "RESTRICTION", "Card blocked/suspended above DPD thresholds",
             dict(block_above_dpd=pol.card_block_dpd, suspend_above_dpd=pol.card_suspend_dpd), pol.card_block_dpd, prod="CC-SYN"),
        rule("ASSET_RECOVERY_REVIEW", "COLLATERAL", "Collateral recovery review opens above DPD threshold",
             dict(review_above_dpd=pol.recovery_review_dpd, repossession_review_above_dpd=pol.repossession_dpd),
             pol.recovery_review_dpd, prod="AF-SYN"),
        rule("PAYMENT_ALLOCATION_LOAN", "ALLOCATION", "Oldest installment first; interest before principal", dict(order=["INTEREST", "PRINCIPAL"])),
        rule("PAYMENT_ALLOCATION_CARD", "ALLOCATION", "Unmet minimums (oldest first), then billed balance, then unbilled",
             dict(order=["MIN_DUE", "BILLED_BALANCE", "UNBILLED"]), prod="CC-SYN"),
    ]
    return dict(branches=branches, products=prod_rows, collection_teams=team_rows, collection_agents=agents,
                collection_policy_rules=rules)
