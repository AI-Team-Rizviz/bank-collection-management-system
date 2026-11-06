"""Portfolio planning (customers, accounts, delinquency targets) and chunked row generation."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator

from seed.config import GenConfig
from seed.generators import customers as cg
from seed.generators.events import build_event_rows
from seed.generators.reference import branch_list, reference_rows
from seed.simulation import financial_rules as fr
from seed.simulation.engine import AccountSim, RawEvent, SimContext
from seed.simulation.financial_rules import ZERO, money
from seed.simulation.scenarios import (AcctPlan, CardPlanner, CustomerPlan, InstallmentPlanner, card_cycle_dues,
                                       installment_dues)
from seed.simulation.timeline import Calendar, add_months, local_dt, rng_for, run_namespace, uid

CATEGORY_PREFIX = {"PERSONAL_LOAN": "LOAN", "CREDIT_CARD": "CARD", "ASSET_FINANCING": "ASSET"}
ASSETS = [  # category, price range (PKR), makes/models (fictional manufacturers)
    ("MOTORCYCLE_70CC", (140_000, 220_000), [("Karakoram Autos", "KA-70"), ("Indus Wheels", "IW-70 Classic")]),
    ("MOTORCYCLE_125CC", (230_000, 340_000), [("Karakoram Autos", "KA-125"), ("Sindh Motors", "SM-125 Deluxe")]),
    ("MOTORCYCLE_150CC", (330_000, 560_000), [("Indus Wheels", "IW-150 Sport"), ("Sindh Motors", "SM-150R")]),
    ("SCOOTY_100CC", (180_000, 290_000), [("Zephyr Scooters", "ZS-100 City"), ("Karakoram Autos", "KA-Scooty")]),
    ("ELECTRIC_SCOOTER", (190_000, 420_000), [("Zephyr Scooters", "ZE-Volt"), ("Indus Wheels", "IW-Electro")]),
    ("ELECTRIC_BIKE", (220_000, 480_000), [("Sindh Motors", "SM-E-Bike")]),
]


def _round_to(x: float, step: int) -> Decimal:
    return Decimal(int(round(x / step) * step))


# ============================================================================== planning
@dataclass
class Portfolio:
    cfg: GenConfig
    customers: list[CustomerPlan]
    accounts: list[AcctPlan]
    by_customer: dict[int, list[AcctPlan]]
    cal: Calendar
    ns: object
    branches: list[dict]


def build_portfolio(cfg: GenConfig) -> Portfolio:
    cal = Calendar(cfg.holidays)
    branches = branch_list()
    ns = run_namespace(cfg.run_id)
    N, A = cfg.n_customers, cfg.n_accounts
    custs = [cg.make_customer_plan(cfg.seed, i) for i in range(N)]
    rng = rng_for(cfg.seed, "allocation")
    # --- how many accounts per customer (richer customers hold more; cap 4)
    slots = [1] * N
    weights = [1.0 + {"LOW": 0, "LOWER_MIDDLE": 0.4, "MIDDLE": 1.0, "UPPER_MIDDLE": 1.6, "HIGH": 2.0}[c.income_band] for c in custs]
    for _ in range(A - N):
        for _try in range(20):
            i = rng.choices(range(N), weights)[0]
            if slots[i] < 4:
                slots[i] += 1
                break
    owners = [i for i in range(N) for _ in range(slots[i])]
    mix = cfg.products
    counts = {"PERSONAL_LOAN": round(len(owners) * mix.personal_loan), "CREDIT_CARD": round(len(owners) * mix.credit_card)}
    counts["ASSET_FINANCING"] = len(owners) - counts["PERSONAL_LOAN"] - counts["CREDIT_CARD"]
    cats = [c for c, k in counts.items() for _ in range(k)]
    rng.shuffle(cats)
    seq: dict[str, int] = defaultdict(int)
    accounts: list[AcctPlan] = []
    pol = cfg.policy
    for n, (ci, cat) in enumerate(zip(owners, cats)):
        cust = custs[ci]
        seq[cat] += 1
        number = f"{CATEGORY_PREFIX[cat]}-{seq[cat]:06d}"
        ar = rng_for(cfg.seed, "acct", number)
        max_days = int(cfg.max_account_age_months * 30.4)
        age = int(cfg.min_account_age_days + (max_days - cfg.min_account_age_days) * ar.betavariate(1.2, 1.5))
        plan = AcctPlan(idx=n, number=number, category=cat, cust=cust, open_date=cfg.as_of_date - timedelta(days=age),
                        branch_idx=ar.randrange(len(branches)))
        plan.anchor_day = min(plan.open_date.day, 28)
        income = float(cust.income)
        if cat == "PERSONAL_LOAN":
            plan.term = ar.choices(pol.loan_terms, pol.loan_term_weights)[0]
            plan.rate = Decimal(str(round(ar.uniform(*pol.loan_rate_range), 2)))
            plan.method = "REDUCING_BALANCE"
            target_emi = income * min(0.45, 0.06 + 0.40 * ar.betavariate(2, 4))
            i = float(plan.rate) / 1200
            ann = (1 - (1 + i) ** -plan.term) / i
            lo, hi = pol.loan_principal_range
            plan.principal = _round_to(min(hi, max(lo, target_emi * ann)), 5000)
        elif cat == "ASSET_FINANCING":
            a_cat, (plo, phi), models = ar.choice(ASSETS)
            price = _round_to(ar.uniform(plo, phi), 1000)
            dp = _round_to(float(price) * ar.uniform(*pol.asset_down_payment_pct), 1000)
            plan.term = ar.choices(pol.asset_terms, pol.asset_term_weights)[0]
            plan.rate = Decimal(str(round(ar.uniform(*pol.asset_rate_range), 2)))
            plan.method = "FLAT_RATE"
            plan.principal = money(price - dp)
            make, model = ar.choice(models)
            plan.asset = dict(category=a_cat, make=make, model=model, price=money(price), down=money(dp),
                              year=plan.open_date.year - ar.choice([0, 0, 0, 1]))
        else:
            plan.credit_limit = _round_to(min(1_500_000, max(25_000, income * ar.uniform(1.0, 3.5))), 5000)
            plan.statement_day = ar.randint(1, 28)
            plan.card_tier = "CLASSIC" if plan.credit_limit < 100_000 else "GOLD" if plan.credit_limit < 300_000 else "PLATINUM"
        if cat != "CREDIT_CARD":
            plan.emi = fr.build_installments(plan.principal, plan.rate, plan.term, plan.method)[0].amount
        accounts.append(plan)
    by_customer: dict[int, list[AcctPlan]] = defaultdict(list)
    for a in accounts:
        by_customer[a.cust.idx].append(a)
    # --- burden -> discipline -> card behaviour (all known at origination except latent z/noise)
    for c in custs:
        obligations = sum((a.emi for a in by_customer[c.idx] if a.category != "CREDIT_CARD"), ZERO)
        obligations += sum((a.credit_limit * Decimal("0.02") for a in by_customer[c.idx] if a.category == "CREDIT_CARD"), ZERO)
        c.obligation = obligations
        burden = float(obligations / c.income)
        r = rng_for(cfg.seed, "discipline", c.idx)
        c.discipline = cg.sigmoid(1.9 - 0.85 * c.z - 1.8 * burden + r.gauss(0, 0.45))
    for a in accounts:
        if a.category == "CREDIT_CARD":
            r = rng_for(cfg.seed, "cardtype", a.number)
            p_trans = cg.sigmoid(0.4 - 0.9 * a.cust.z + r.gauss(0, 0.5))      # low-risk -> transactor
            a.card_type = r.choices(["TRANSACTOR", "MIXED", "REVOLVER"], [p_trans * 100, 40, (1 - p_trans) * 80])[0]
            a.spend_ratio = max(0.04, min(0.6, r.uniform(0.05, 0.3) + 0.05 * a.cust.z + (0.08 if a.card_type == "REVOLVER" else 0)))
    _assign_scenarios(cfg, cal, accounts)
    return Portfolio(cfg, custs, accounts, by_customer, cal, ns, branches)


def _dues(cfg, cal, a: AcctPlan) -> list[date]:
    if a.category == "CREDIT_CARD":
        return card_cycle_dues(a, cfg.as_of_date, cal, cfg.policy.card_statement_due_days)
    return installment_dues(a, cal)


def _candidates(a: AcctPlan, dues: list[date], as_of: date, lo: int, hi: int) -> list[int]:
    min_no = 2 if (a.category == "CREDIT_CARD") else 1
    return [k for k, d in enumerate(dues, start=1) if k >= min_no and lo <= (as_of - d).days <= hi]


def _assign_scenarios(cfg: GenConfig, cal: Calendar, accounts: list[AcctPlan]) -> None:
    as_of = cfg.as_of_date
    rng = rng_for(cfg.seed, "scenarios")
    dues = {a.number: _dues(cfg, cal, a) for a in accounts}
    taken: set[str] = set()
    inst = [a for a in accounts if a.category != "CREDIT_CARD"]
    # explicit scenario accounts (excluded from the delinquency-quota pool)
    for a in rng.sample(inst, len(inst)):
        if rng.random() > 0.035 or a.number in taken:
            continue
        cands = _candidates(a, dues[a.number], as_of, 130, 320)
        if cands and a.term >= 12:
            a.onset = rng.choice(cands)
            a.restructure_on = dues[a.number][a.onset - 1] + timedelta(days=rng.randint(65, 95))
            a.scenarios.add("RESTRUCTURED")
            taken.add(a.number)
    for a in rng.sample(inst, len(inst)):
        if a.number in taken or rng.random() > 0.045 or a.term < 12:
            continue
        ds = dues[a.number]
        ks = [k for k in range(int(a.term * 0.35), int(a.term * 0.85) + 1) if k >= 3 and (as_of - ds[k - 1]).days >= 25]
        if ks:
            a.settle_after_no = rng.choice(ks)
            a.scenarios.add("EARLY_SETTLEMENT")
            taken.add(a.number)
    for a in accounts:
        if a.category == "CREDIT_CARD" and a.number not in taken and rng.random() < 0.035:
            n = len(dues[a.number])
            if n >= 9:
                a.close_cycle = rng.randint(4, n - 4)
                a.scenarios.add("ACCOUNT_CLOSURE")
                taken.add(a.number)
    # delinquency targets: fill worst buckets first, ranking by (noisy) latent risk + burden
    mix = cfg.delinquency
    total = len(accounts)
    plan_order = [("DPD_90_PLUS", mix.dpd_90_plus, 91, 330), ("DPD_61_90", mix.dpd_61_90, 61, 90),
                  ("DPD_31_60", mix.dpd_31_60, 31, 60), ("DPD_1_30", mix.dpd_1_30, 1, 30)]
    rank = {a.number: a.cust.z + 2.0 * float(a.cust.obligation / a.cust.income) + rng.gauss(0, 1.2) for a in accounts}
    ordered = sorted((a for a in accounts if a.number not in taken), key=lambda a: -rank[a.number])
    for bucket, share, lo, hi in plan_order:
        quota = round(share * total)
        for a in ordered:
            if quota <= 0:
                break
            if a.number in taken:
                continue
            cands = _candidates(a, dues[a.number], as_of, lo, hi)
            if not cands:
                continue
            a.target_bucket, a.onset = bucket, rng.choice(cands)
            taken.add(a.number)
            quota -= 1


# ============================================================================== generation
def _asset_collateral(sim: AccountSim, plan: AcctPlan, ar) -> dict:
    pol, a = sim.pol, plan.asset
    n = int(plan.number.split("-")[1])
    status, released, review, repo = "LIEN_ACTIVE", None, None, None
    if sim.closed_date:
        status, released = "LIEN_RELEASED", sim.closed_date
    elif sim.bucket == "DPD_90_PLUS":
        oldest = fr.oldest_unmet(sim.obls, sim.tol)
        status = "UNDER_RECOVERY_REVIEW"
        review = min(sim.as_of, (oldest.eff_due + timedelta(days=pol.recovery_review_dpd + 1 + ar.randint(2, 9))))
        repo_date = oldest.eff_due + timedelta(days=pol.repossession_dpd + ar.randint(2, 20))
        if sim.dpd_now > pol.repossession_dpd + 20 and repo_date <= sim.as_of and ar.random() < 0.5:
            status, repo = "REPOSSESSED", repo_date
    return dict(asset_id=uid(sim.ctx.ns, "asset", plan.number), account_id=sim.account_id, asset_category=a["category"],
                make=a["make"], model_name=a["model"], model_year=a["year"], registration_number=f"SYN-REG-{n:06d}",
                chassis_number=f"SYN-CH-{n:08d}", engine_number=f"SYN-EN-{n:08d}", purchase_price=a["price"],
                down_payment=a["down"], financed_amount=a["price"] - a["down"], collateral_status=status,
                lien_marked_on=plan.open_date, lien_released_on=released, recovery_review_opened_on=review, repossessed_on=repo)


def _risk_rows(cfg, ns, cust: CustomerPlan, sims: list[AccountSim], customer_id, since_open: date):
    rng = rng_for(cfg.seed, "risk", cust.idx)
    orig_accts = [s for s in sims if s.open_date == since_open]
    orig_obl = sum((s.plan.emi for s in orig_accts if not s.is_card), ZERO) + sum(
        (s.plan.credit_limit * Decimal("0.02") for s in orig_accts if s.is_card), ZERO)
    burden0 = float(orig_obl / cust.income)
    emp_adj = {"DAILY_WAGE": 6, "SELF_EMPLOYED": 3, "REMITTANCE_DEPENDENT": 2, "BUSINESS_OWNER": 1}.get(cust.employment, 0)
    base = 30 + 12 * (0.5 * cust.z + rng.gauss(0, 0.8)) + 45 * burden0 + emp_adj
    clamp = lambda x: max(0.0, min(100.0, x))
    band = lambda s: "LOW" if s < 25 else "MEDIUM" if s < 45 else "HIGH" if s < 65 else "VERY_HIGH"
    active = [s for s in sims if not s.closed_date]
    missed = sum(s.missed_12m for s in sims)
    max_dpd = max((s.max_dpd_12m for s in sims), default=0)
    cards = [s for s in active if s.is_card]
    util = None
    if cards:
        util = sum(float((s.billed + s.unbilled) / s.plan.credit_limit) for s in cards) / len(cards)
    now_obl = sum((Decimal(str(s.details["installment_amount"])) for s in active if not s.is_card), ZERO) + sum(
        (s.statements[-1].minimum for s in cards if s.statements), ZERO)
    exposure = sum(((s.billed + s.unbilled) if s.is_card else s.principal_bal for s in active), ZERO)
    score_now = clamp(base + 6 * min(missed, 5) + 0.12 * min(max_dpd, 180) + (10 * max(0.0, util - 0.7) if util else 0))
    score0 = clamp(base)
    d = lambda x: Decimal(str(round(x, 2)))
    common = dict(customer_id=customer_id, model_version="synthetic-rules-v1")
    rows = [
        dict(risk_profile_id=uid(ns, "risk", cust.idx, "orig"), effective_date=since_open, profile_source="ORIGINATION",
             risk_score=d(score0), risk_band=band(score0), monthly_income=cust.income, monthly_obligation=orig_obl,
             burden_ratio=Decimal(str(round(burden0, 4))), active_account_count=len(orig_accts),
             total_exposure=sum((s.plan.principal if not s.is_card else s.plan.credit_limit for s in orig_accts), ZERO),
             max_dpd_12m=0, missed_payment_count_12m=0, avg_card_utilization=None, **common),
        dict(risk_profile_id=uid(ns, "risk", cust.idx, "asof"), effective_date=cfg.as_of_date, profile_source="BEHAVIORAL_AS_OF",
             risk_score=d(score_now), risk_band=band(score_now), monthly_income=cust.income, monthly_obligation=now_obl,
             burden_ratio=Decimal(str(round(float(now_obl / cust.income), 4))), active_account_count=len(active),
             total_exposure=exposure, max_dpd_12m=max_dpd, missed_payment_count_12m=missed,
             avg_card_utilization=Decimal(str(round(util, 4))) if util is not None else None, **common),
    ]
    first_sim = min(sims, key=lambda s: (s.open_date, s.plan.number))
    evs = [RawEvent(local_dt(since_open, 11), "RISK_PROFILE_UPDATED", "orig", dict(
               profile_source="ORIGINATION", risk_score=rows[0]["risk_score"], risk_band=rows[0]["risk_band"], customer_ref=f"CUST-{cust.idx + 1:06d}")),
           RawEvent(local_dt(cfg.as_of_date, 23, 30), "RISK_PROFILE_UPDATED", "asof", dict(
               profile_source="BEHAVIORAL_AS_OF", risk_score=rows[1]["risk_score"], risk_band=rows[1]["risk_band"],
               customer_ref=f"CUST-{cust.idx + 1:06d}"))]
    return rows, first_sim, evs


def generate_chunks(cfg: GenConfig, pf: Portfolio | None = None) -> Iterator[tuple[str, dict[str, list[dict]]]]:
    """Yield ('reference', rows) then ('chunk-N', rows) for customer batches; each chunk is FK-complete."""
    pf = pf or build_portfolio(cfg)
    yield "reference", reference_rows(cfg)
    ctx = SimContext(cfg, pf.cal, pf.ns)
    cat_to_product = {c: uid_ for c, uid_ in ((r["category"], r["product_id"]) for r in reference_rows(cfg)["products"])}
    for start in range(0, cfg.n_customers, cfg.chunk_customers):
        rows: dict[str, list[dict]] = defaultdict(list)
        for cust in pf.customers[start:start + cfg.chunk_customers]:
            plans = pf.by_customer[cust.idx]
            sims = []
            for plan in plans:
                planner = CardPlanner() if plan.category == "CREDIT_CARD" else InstallmentPlanner()
                sims.append(AccountSim(ctx, plan, rng_for(cfg.seed, "sim", plan.number)).run(planner))
            since_open = min(s.open_date for s in sims)
            customer_id = uid(pf.ns, "customer", cust.idx)
            since = since_open - timedelta(days=rng_for(cfg.seed, "since", cust.idx).randint(0, 1800))
            rows["customers"].append(cg.customer_row(cfg, pf.ns, cust, pf.branches, since))
            risk_rows, first_sim, risk_events = _risk_rows(cfg, pf.ns, cust, sims, customer_id, since_open)
            rows["risk_profiles"].extend(risk_rows)
            for sim in sims:
                plan = sim.plan
                ar = rng_for(cfg.seed, "asset", plan.number)
                rows["accounts"].append(dict(
                    account_id=sim.account_id, run_id=cfg.run_id, account_number=plan.number, customer_id=customer_id,
                    product_id=cat_to_product[plan.category], branch_id=pf.branches[plan.branch_idx]["branch_id"],
                    currency=cfg.currency, status="CLOSED" if sim.closed_date else "ACTIVE", opened_date=plan.open_date,
                    closed_date=sim.closed_date, close_reason=sim.close_reason, is_restructured=sim.restructure_info is not None))
                if sim.is_card:
                    rows["credit_card_details"].append(sim.details)
                    rows["card_statements"].extend(st.row for st in sim.statements)
                else:
                    rows["loan_details"].append(sim.details)
                    rows["repayment_schedules"].extend(_schedule_row(sim, o) for o in sim.obls)
                    if plan.asset:
                        rows["financed_assets"].append(_asset_collateral(sim, plan, ar))
                rows["ledger_entries"].extend(sim.ledger)
                rows["payment_transactions"].extend(sim.txns)
                rows["payment_allocations"].extend(sim.allocs)
                rows["account_balance_snapshots"].extend(sim.bsnaps.values())
                rows["delinquency_snapshots"].extend(sim.dsnaps.values())
                ev, dl = build_event_rows(cfg, pf.ns, sim, customer_id, risk_events if sim is first_sim else ())
                rows["banking_events"].extend(ev)
                rows["event_delivery_status"].extend(dl)
        yield f"chunk-{start // cfg.chunk_customers + 1:05d}", dict(rows)


def _schedule_row(sim: AccountSim, o) -> dict:
    return dict(schedule_id=o.oid, account_id=sim.account_id, schedule_version=o.version, installment_no=o.no,
                due_date=o.due_date, effective_due_date=o.eff_due, opening_principal=o.extra["opening_principal"],
                principal_due=o.due["PRINCIPAL"], interest_due=o.due["INTEREST"], total_due=o.total_due,
                principal_paid=o.paid["PRINCIPAL"], interest_paid=o.paid["INTEREST"], interest_waived=o.interest_waived,
                status=o.status, last_payment_effective_date=o.last_payment_effective_date(), superseded_on=o.superseded_on)
