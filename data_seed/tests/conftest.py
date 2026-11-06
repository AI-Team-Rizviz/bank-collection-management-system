from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from seed.config import GenConfig
from seed.simulation.engine import AccountSim, SimContext
from seed.simulation.financial_rules import ZERO
from seed.simulation.scenarios import AcctPlan, CardPlanner, CustomerPlan, InstallmentPlanner
from seed.simulation.timeline import Calendar, local_dt, rng_for, run_namespace, uid

D = Decimal


def make_cfg(as_of: date, **kw) -> GenConfig:
    return GenConfig(profile="custom", customers=1, as_of_date=as_of, holidays=[], **kw)


def customer(idx=0) -> CustomerPlan:
    return CustomerPlan(idx=idx, z=0.0, discipline=0.9, income=D("100000"), income_band="MIDDLE", employment="SALARIED")


class ScriptedLoan(InstallmentPlanner):
    """Golden-test planner: no random behaviour, only explicitly scripted actions."""

    def __init__(self, payments=(), reversals=(), restructure=None):
        self.payments, self.reversals, self.restructure = payments, reversals, restructure

    def plan_installments(self, sim, *a, **kw):
        return None

    def setup(self, sim):
        super().setup(sim)
        for when, amount, *rest in self.payments:
            posted = rest[0] if rest else when
            sim.push(posted, "PAY", dict(initiated=when, rule=("FIXED", D(amount)), channel="RAAST", context="REGULAR",
                                         reversal=None, back_valued=posted.date() > when.date()))
        for when, idx in self.reversals:
            sim.push(when, "REVERSE", dict(orig=uid(sim.ctx.ns, "acct", sim.plan.number, "txn", idx), reason="CHEQUE_RETURNED"))
        if self.restructure:
            sim.push(self.restructure[0], "RESTRUCTURE", self.restructure[1])


def make_loan(open_date, principal, term, as_of, *, rate="0", method="REDUCING_BALANCE", number="LOAN-GOLD01",
              payments=(), reversals=(), restructure=None, cust=None):
    cfg = make_cfg(as_of)
    ctx = SimContext(cfg, Calendar([]), run_namespace("golden"))
    plan = AcctPlan(idx=0, number=number, category="PERSONAL_LOAN", cust=cust or customer(), open_date=open_date, branch_idx=0,
                    principal=D(principal), term=term, rate=D(rate), method=method, anchor_day=open_date.day)
    sim = AccountSim(ctx, plan, rng_for(1, number))
    return sim.run(ScriptedLoan(payments, reversals, restructure))


class ScriptedCard(CardPlanner):
    def __init__(self, purchases=(), payments=()):
        self.purchases, self.payments = purchases, payments

    def plan_purchases(self, sim, *a, **kw):
        return None

    def plan_card_payments(self, sim, *a, **kw):
        return None

    def setup(self, sim):
        super().setup(sim)
        self.episodes, self.cures = {}, set()
        for when, amount in self.purchases:
            sim.push(when, "PURCHASE", dict(amount=D(amount), c=1))
        for when, amount in self.payments:
            sim.push(when, "PAY", dict(initiated=when, rule=("FIXED", D(amount)), channel="RAAST", context="REGULAR",
                                       reversal=None, back_valued=False))


def make_card(open_date, as_of, *, limit="100000", statement_day=20, purchases=(), payments=(), number="CARD-GOLD01", cust=None):
    cfg = make_cfg(as_of)
    ctx = SimContext(cfg, Calendar([]), run_namespace("golden"))
    plan = AcctPlan(idx=0, number=number, category="CREDIT_CARD", cust=cust or customer(), open_date=open_date, branch_idx=0,
                    credit_limit=D(limit), statement_day=statement_day)
    return AccountSim(ctx, plan, rng_for(1, number)).run(ScriptedCard(purchases, payments))


def at(y, m, d, hh=10, mm=0):
    return local_dt(date(y, m, d), hh, mm)


def dpd_on(sim, d: date, reason=None):
    """Delinquency snapshot recorded for date d (prefers AS_OF / MONTH_END / TRANSITION)."""
    for (dt, r), row in sim.dsnaps.items():
        if dt == d and (reason is None or r == reason):
            return row
    return None
