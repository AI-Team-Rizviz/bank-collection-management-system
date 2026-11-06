"""Fictional customer profiles. No real identities: placeholders only (see README)."""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from seed.generators.reference import FIRST, LAST
from seed.simulation.financial_rules import money
from seed.simulation.scenarios import CustomerPlan
from seed.simulation.timeline import rng_for, uid

BANDS = [  # name, probability, income range (PKR / month)
    ("LOW", 0.28, (25_000, 50_000)), ("LOWER_MIDDLE", 0.32, (50_000, 100_000)), ("MIDDLE", 0.22, (100_000, 200_000)),
    ("UPPER_MIDDLE", 0.12, (200_000, 400_000)), ("HIGH", 0.06, (400_000, 1_500_000)),
]
EMPLOYMENT = {  # type: (weight, latent-risk shift)
    "SALARIED": (50, -0.15), "SELF_EMPLOYED": (22, 0.15), "BUSINESS_OWNER": (10, 0.0),
    "DAILY_WAGE": (8, 0.35), "PENSIONER": (5, -0.2), "REMITTANCE_DEPENDENT": (5, 0.05),
}
GENDERS = ["FEMALE", "MALE"]


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def make_customer_plan(seed: int, idx: int) -> CustomerPlan:
    rng = rng_for(seed, "cust", idx)
    band = rng.choices(BANDS, [b[1] for b in BANDS])[0]
    lo, hi = band[2]
    income = money(Decimal(str(round(math.exp(rng.uniform(math.log(lo), math.log(hi))) / 500) * 500)))
    emp = rng.choices(list(EMPLOYMENT), [v[0] for v in EMPLOYMENT.values()])[0]
    band_idx = [b[0] for b in BANDS].index(band[0])
    # latent risk: employment stability + mild income effect + idiosyncratic noise.
    # Deliberately independent of gender, age and city (no protected-attribute correlation).
    z = rng.gauss(0, 1) + EMPLOYMENT[emp][1] - 0.08 * (band_idx - 2)
    return CustomerPlan(idx=idx, z=z, discipline=0.85, income=income, income_band=band[0], employment=emp)


def customer_row(cfg, ns, plan: CustomerPlan, branches: list[dict], since: date) -> dict:
    rng = rng_for(cfg.seed, "cust-demo", plan.idx)
    from seed.generators.reference import CITIES
    city_pool = [c for c in CITIES for _ in range(c[2])]
    city, prov, _ = rng.choice(city_pool)
    local_branches = [b for b in branches if b["city"] == city]
    return dict(
        customer_id=uid(ns, "customer", plan.idx), run_id=cfg.run_id, customer_ref=f"CUST-{plan.idx + 1:06d}",
        full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", gender=rng.choice(GENDERS),
        birth_year=rng.randint(1955, 2003), city=city, province=prov, employment_type=plan.employment,
        income_band=plan.income_band, monthly_income=plan.income,
        national_id_token=f"SYN-ID-{plan.idx + 1:08d}", phone_placeholder=f"+92-000-{plan.idx + 1:07d}",
        email_placeholder=f"customer{plan.idx + 1:06d}@example.invalid",
        home_branch_id=rng.choice(local_branches)["branch_id"], customer_since=since, kyc_status="VERIFIED", status="ACTIVE")
