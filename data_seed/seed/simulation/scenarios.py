"""Behaviour planners: translate customer/account profiles + explicit scenarios into dated actions.

The planners only decide WHAT the customer does and WHEN; all balances, allocations, DPD and
delinquency state are derived by replaying those actions in `engine.AccountSim`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from seed.simulation import financial_rules as fr
from seed.simulation.engine import PRIO_STATEMENT, CardStmt
from seed.simulation.financial_rules import ZERO, Obligation, money
from seed.simulation.timeline import add_months, local_dt, uid

LAST_RULE = ("CLEAR_ALL",)   # final installment: clears everything outstanding (absorbs any rounding dust)


@dataclass
class CustomerPlan:
    idx: int
    z: float                   # latent risk (internal driver, standard normal)
    discipline: float          # 0..1 payment discipline (derived from z, burden, noise)
    income: Decimal
    income_band: str
    employment: str
    obligation: Decimal = ZERO  # planned monthly obligations (EMIs + est. card minimums)


@dataclass
class AcctPlan:
    idx: int
    number: str
    category: str
    cust: CustomerPlan
    open_date: date
    branch_idx: int
    # installment products
    principal: Decimal = ZERO
    term: int = 0
    rate: Decimal = ZERO
    method: str = ""
    anchor_day: int = 1
    emi: Decimal = ZERO
    asset: dict | None = None
    # cards
    credit_limit: Decimal = ZERO
    statement_day: int = 1
    card_tier: str = "CLASSIC"
    card_type: str = "MIXED"
    spend_ratio: float = 0.2
    # behaviour
    target_bucket: str = fr.CURRENT
    onset: int | None = None            # installment no / card cycle where payments stop
    scenarios: set = field(default_factory=set)
    settle_after_no: int | None = None
    restructure_on: date | None = None
    close_cycle: int | None = None
    disc_mult: float = 1.0
    due_dates: list[date] = field(default_factory=list)   # contractual due dates (planning aid)


def first_statement_date(open_date: date, statement_day: int) -> date:
    first = add_months(open_date + timedelta(days=14), 0, statement_day)
    return first if first >= open_date + timedelta(days=14) else add_months(first, 1, statement_day)


def card_cycle_dues(plan: "AcctPlan", as_of: date, cal, due_days: int) -> list[date]:
    """Effective due dates of every statement cycle that closes on/before as_of."""
    s1, out, c = first_statement_date(plan.open_date, plan.statement_day), [], 1
    while add_months(s1, c - 1, plan.statement_day) <= as_of:
        out.append(cal.next_business_day(add_months(s1, c - 1, plan.statement_day) + timedelta(days=due_days)))
        c += 1
    return out


def installment_dues(plan: "AcctPlan", cal) -> list[date]:
    first = add_months(plan.open_date, 1, plan.anchor_day)
    return [cal.next_business_day(add_months(first, k, plan.anchor_day)) for k in range(plan.term)]


def _ceil_to(x: Decimal, step: int) -> Decimal:
    return Decimal(math.ceil(x / step) * step)


def _rand_date(rng, lo: date, hi: date, tail: float = 6.0) -> date:
    """Date in [lo, hi], skewed toward lo (late payers cluster shortly after the due date)."""
    span = (hi - lo).days
    return lo + timedelta(days=min(span, int(rng.expovariate(1 / tail))))


# =============================================================================== installments
class InstallmentPlanner:
    """Personal loans (REDUCING_BALANCE) and asset financing (FLAT_RATE)."""

    # ---- schedule ------------------------------------------------------------------------
    def _make_obligations(self, sim, version, principal, rate, n, first_due, anchor, method):
        insts = fr.build_installments(principal, rate, n, method)
        out = []
        for ins in insts:
            due = add_months(first_due, ins.no - 1, anchor)
            ob = Obligation(oid=uid(sim.ctx.ns, "sched", sim.plan.number, version, ins.no), kind="INSTALLMENT", no=ins.no,
                            due_date=due, eff_due=sim.cal.next_business_day(due),
                            due={"INTEREST": ins.interest, "PRINCIPAL": ins.principal}, version=version,
                            extra={"opening_principal": ins.opening_principal})
            out.append(ob)
        sim.obls.extend(out)
        return insts, out

    def setup(self, sim):
        p, cfg = sim.plan, sim.cfg
        first_due = add_months(p.open_date, 1, p.anchor_day)
        insts, obls = self._make_obligations(sim, 1, p.principal, p.rate, p.term, first_due, p.anchor_day, p.method)
        sim.schedule_version = 1
        sim.principal_bal = p.principal
        sim.ledger.append(dict(entry_id=sim.new_id("ledger"), account_id=sim.account_id, entry_type="DISBURSEMENT",
                               amount=p.principal, entry_date=p.open_date, posted_at=local_dt(p.open_date, 10)))
        total_markup = sum((i.interest for i in insts), ZERO)
        sim.details = dict(account_id=sim.account_id, original_principal=p.principal, term_months=p.term,
                           annual_markup_rate=p.rate, calculation_method=p.method, disbursement_date=p.open_date,
                           first_due_date=first_due, maturity_date=obls[-1].due_date, installment_amount=insts[0].amount,
                           total_scheduled_markup=total_markup, current_schedule_version=1, restructured_on=None,
                           restructured_principal=None, early_settlement_date=None, early_settlement_amount=None)
        sim.emit(local_dt(p.open_date, 9), "ACCOUNT_CREATED", "created", dict(
            product_category=p.category, opened_date=p.open_date, currency=cfg.currency))
        sim.emit(local_dt(p.open_date, 10), "LOAN_DISBURSED", "disbursed", dict(
            principal=p.principal, term_months=p.term, annual_markup_rate=p.rate, calculation_method=p.method,
            installment_amount=insts[0].amount, first_due_date=first_due, maturity_date=obls[-1].due_date))
        if p.restructure_on:
            self.plan_installments(sim, 1, onset_no=p.onset, end_date=p.restructure_on)
            sim.push(local_dt(p.restructure_on, 11), "RESTRUCTURE", {})
        elif p.settle_after_no:
            self.plan_installments(sim, 1, stop_after=p.settle_after_no)
            k = next(o for o in obls if o.no == p.settle_after_no)
            nxt = next((o for o in obls if o.no == k.no + 1), None)
            hi = min((nxt.eff_due - timedelta(days=3)) if nxt else sim.as_of, sim.as_of - timedelta(days=1))
            lo = k.eff_due + timedelta(days=3)
            if hi >= lo:
                sim.push(sim.rand_time(lo + timedelta(days=sim.rng.randint(0, (hi - lo).days)), 10, 16), "SETTLE", {})
        else:
            self.plan_installments(sim, 1, onset_no=p.onset)

    # ---- planning ------------------------------------------------------------------------
    def plan_installments(self, sim, version, onset_no=None, end_date=None, stop_after=None):
        rng, as_of, p = sim.rng, sim.as_of, sim.plan
        obls = [o for o in sim.obls if o.version == version and o.active]
        due_now = [o for o in obls if o.eff_due <= as_of and (stop_after is None or o.no <= stop_after)]
        last_no = obls[-1].no
        disc = min(0.995, max(0.05, p.cust.discipline * p.disc_mult))
        hard_end = (end_date - timedelta(days=1)) if end_date else as_of - timedelta(days=1)
        can_episode = onset_no is None or onset_no > 3
        p_ep = min(0.55, 0.03 + 1.3 * (1 - disc) ** 1.3) if stop_after is None else 0.0
        episodes = {}
        used: set[int] = set()
        if can_episode and rng.random() < p_ep:
            cands = [o.no for o in due_now if 2 <= o.no <= (onset_no or last_no) - 3]
            for _ in range(1 if rng.random() < 0.75 else 2):
                if not cands:
                    break
                s, m = rng.choice(cands), rng.choice([1, 1, 1, 2, 2, 3, 4])
                span = set(range(s - 1, s + m + 2))
                if span & used or s + m >= (onset_no or last_no + 5) - 1:
                    continue
                episodes[s] = m
                used |= span
        by_no = {o.no: o for o in obls}
        covered: set[int] = set()
        for o in due_now:
            if o.no in covered:
                continue
            if onset_no is not None and o.no >= onset_no:
                self._plan_tail(sim, o, end_date)
                break
            nxt = by_no.get(o.no + 1)
            limit = (nxt.eff_due - timedelta(days=1)) if nxt else as_of - timedelta(days=1)
            limit = min(limit, hard_end) if end_date else min(limit, as_of - timedelta(days=1))
            if stop_after is not None and o.no == stop_after:
                limit = o.eff_due                                    # settlement candidates pay on/before due
            if o.no in episodes and self._plan_episode(sim, o, by_no, episodes[o.no], covered, due_now, hard_end):
                continue
            self._plan_normal(sim, o, nxt, limit, disc, last_no, hard_end, stop_after is not None and o.no == stop_after)

    def _pay_rule(self, o, last_no, style):
        A = o.total_due
        if o.no == last_no:
            return LAST_RULE
        if style == "UP":
            return ("FIXED", _ceil_to(A, 10))
        if style == "DOWN" and A != A.to_integral_value():
            return ("FIXED", fr.money(int(A)))      # rounding edge: leaves < PKR 1 short (within tolerance)
        return ("FIXED", A)

    def _plan_normal(self, sim, o, nxt, limit, disc, last_no, hard_end, no_late):
        rng, as_of, open_d = sim.rng, sim.as_of, sim.open_date
        e = o.eff_due
        p_late = 0.02 + 0.45 * (1 - disc) ** 1.5
        p_part = 0.012 + 0.10 * (1 - disc)
        style = rng.choices(["EXACT", "UP", "DOWN"], [90, 7, 3])[0]
        if style == "DOWN":
            # at most ONE rounded-down payment per account so total dust stays below the PKR 1.00 tolerance
            style = "EXACT" if getattr(sim, "dust_used", False) else "DOWN"
            sim.dust_used = True
        rule = self._pay_rule(o, last_no, style)
        u = rng.random()
        room = min((limit - e).days, (hard_end - e).days)
        if not no_late and room >= 1 and u < p_late:
            late = min(room, rng.randint(1, 25))
            d = e + timedelta(days=rng.randint(1, late))
            ctx = "POST_COLLECTION_FOLLOWUP" if (d - e).days >= 10 else "REGULAR"
            sim.schedule_payment(sim.rand_time(d), rule, context=ctx, deadline=limit)
            return
        if not no_late and room >= 4 and u < p_late + p_part:
            first = money(o.total_due * Decimal(str(round(rng.uniform(0.3, 0.7), 2))))
            sim.schedule_payment(sim.rand_time(e), ("FIXED", first), deadline=limit)
            d2 = e + timedelta(days=rng.randint(3, min(room, 18)))
            sim.schedule_payment(sim.rand_time(d2), rule if o.no == last_no else ("FIXED", o.total_due - first), deadline=limit)
            return
        pay_day = e - timedelta(days=rng.randint(1, 6)) if rng.random() < 0.18 else e - timedelta(days=rng.choice([0, 0, 0, 1]))
        pay_day = max(pay_day, open_d + timedelta(days=1))
        if pay_day > as_of:
            return
        if pay_day == as_of and e == as_of and rng.random() < 0.4:
            # initiated on the reference date and still in flight: PENDING, not yet allocated, not yet overdue
            sim.schedule_payment(sim.rand_time(pay_day, 8, 20), ("FIXED", o.total_due), outcome="PENDING")
            return
        if rng.random() < 0.012 and (limit - pay_day).days >= 3 and hard_end >= pay_day + timedelta(days=3) and not no_late:
            sim.schedule_payment(sim.rand_time(pay_day), ("FIXED", o.total_due), outcome="FAIL",
                                 failure_reason=rng.choice(["INSUFFICIENT_FUNDS", "CHANNEL_TIMEOUT", "LIMIT_EXCEEDED"]))
            pay_day = min(limit, pay_day + timedelta(days=rng.randint(1, 3)))
        rev = None
        if rng.random() < 0.006 and not no_late:
            k = rng.randint(1, 4)
            repay = pay_day + timedelta(days=k + rng.randint(1, 6))
            if repay <= limit and repay <= hard_end:
                rev = dict(after_days=k, reason=rng.choice(["CHEQUE_RETURNED", "IBFT_RETURN", "CUSTOMER_DISPUTE"]))
                sim.schedule_payment(sim.rand_time(repay), LAST_RULE if o.no == last_no else ("FIXED", o.total_due),
                                     deadline=limit)
        if rev:
            # reversed payment must post before the reversal
            sim.schedule_payment(sim.rand_time(pay_day), rule, reversal=rev, deadline=pay_day + timedelta(days=1),
                                 allow_delay=False)
        else:
            sim.schedule_payment(sim.rand_time(pay_day), rule, deadline=limit)

    def _plan_episode(self, sim, o, by_no, m, covered, due_now, hard_end) -> bool:
        rng, as_of = sim.rng, sim.as_of
        missed = [by_no.get(o.no + i) for i in range(m)]
        if any(x is None or x not in due_now for x in missed):
            return False
        nxt = by_no.get(o.no + m)
        lo = missed[-1].eff_due + timedelta(days=1)
        # cure must land before the customer's next regular payment (earliest: 6 days before due), else FIFO
        # allocation would let that payment consume the arrears and shift every later payment by one installment
        hi = min(((nxt.eff_due - timedelta(days=7)) if nxt else as_of - timedelta(days=1)), as_of - timedelta(days=1), hard_end)
        on_next = nxt is not None and nxt.eff_due <= as_of and nxt.eff_due <= hard_end + timedelta(days=1)
        style = rng.choice(["WINDOW", "ON_NEXT", "PARTIAL"]) 
        if style == "ON_NEXT" and not on_next:
            style = "WINDOW"
        if style == "PARTIAL" and (hi - lo).days < 5:
            style = "WINDOW"
        if style == "WINDOW" and hi < lo:
            if not on_next:
                return False
            style = "ON_NEXT"
        for x in missed:
            covered.add(x.no)
        first_due = o.eff_due
        if style == "ON_NEXT":
            covered.add(nxt.no)
            sim.schedule_payment(sim.rand_time(nxt.eff_due), ("DUE_TO_DATE",), deadline=nxt.eff_due + timedelta(days=1),
                                 context="REGULAR", allow_delay=False)
            return True
        d = _rand_date(rng, lo, hi, tail=9.0)
        ctx = "POST_COLLECTION_FOLLOWUP" if (d - first_due).days >= 10 else "REGULAR"
        if style == "PARTIAL":
            arrears = sum((x.total_due for x in missed), ZERO)
            part_day = lo + timedelta(days=rng.randint(0, max(0, (d - lo).days - 3)))
            sim.schedule_payment(sim.rand_time(part_day), ("FIXED", money(arrears * Decimal("0.5"))), deadline=d, context=ctx)
            d = max(d, part_day + timedelta(days=3))
            d = min(d, hi)
        sim.schedule_payment(sim.rand_time(d), ("DUE_TO_DATE",), deadline=hi, context=ctx)
        return True

    def _plan_tail(self, sim, o, end_date):
        """Payments stop at installment `o`: leave it (and everything after) unpaid, with optional
        failed attempt and small partial payments that can never clear the oldest installment."""
        rng, as_of = sim.rng, sim.as_of
        A, e = o.total_due, o.eff_due
        budget = money(A * Decimal("0.8"))
        sim.tail_budget = budget
        last = min(as_of - timedelta(days=1), (end_date - timedelta(days=1)) if end_date else as_of)
        if rng.random() < 0.25 and e <= last:
            sim.schedule_payment(sim.rand_time(e), ("FIXED", A), outcome="FAIL",
                                 failure_reason=rng.choice(["INSUFFICIENT_FUNDS", "ACCOUNT_BLOCKED", "CHANNEL_TIMEOUT"]))
        committed = ZERO
        for _ in range(rng.choice([0, 0, 1, 1, 2])):
            lo, hi = e + timedelta(days=2), last
            if hi < lo:
                break
            amt = money(A * Decimal(str(round(rng.uniform(0.1, 0.4), 2))))
            if committed + amt > budget:
                break
            committed += amt
            sim.schedule_payment(sim.rand_time(lo + timedelta(days=rng.randint(0, (hi - lo).days))), ("FIXED", amt),
                                 context="POST_COLLECTION_FOLLOWUP", deadline=hi)

    # ---- handlers --------------------------------------------------------------------------
    def handle_pay(self, sim, dt, data):
        sim.on_pay(dt, data)

    def handle_reverse(self, sim, dt, data):
        sim.on_reverse(dt, data)

    def handle_settle(self, sim, dt, data):
        """Early settlement payoff = outstanding principal + the interest component of the next
        unpaid installment (plus anything already due). Interest on later installments is waived."""
        if sim.closed_date:
            return
        d = dt.date()
        dpd, *_ = fr.compute_dpd(sim.obls, d, sim.tol)
        if dpd > 0:
            return
        todo = [o for o in sim.obls if o.active and o.remaining() > 0]
        if not todo:
            return
        plan, first_future = [], True
        waived: dict = {}
        for o in todo:
            if o.eff_due <= d or first_future:
                comps = ("INTEREST", "PRINCIPAL")
                if o.eff_due > d:
                    first_future = False
            else:
                comps = ("PRINCIPAL",)
                waived[o] = o.remaining("INTEREST")
            for c in comps:
                if o.remaining(c) > 0:
                    plan.append((o, c, o.remaining(c)))
        amount = sum((a for *_, a in plan), ZERO)
        tid = sim.new_id("txn")
        n = sim.counters["txn"]
        row = dict(transaction_id=tid, account_id=sim.account_id, txn_type="PAYMENT", status="POSTED", amount=amount,
                   currency=sim.cfg.currency, channel="BRANCH_CASH" if sim.cal.is_business_day(d) else "RAAST",
                   initiated_at=dt, posted_at=dt, effective_date=d, reverses_transaction_id=None, reversal_reason=None,
                   failure_reason=None, payment_context="EARLY_SETTLEMENT", idempotency_key=f"{sim.plan.number}:PAY:{n:05d}")
        sim.txns.append(row)
        sim.txn_by_id[tid] = row
        sim._apply_plan(tid, plan, d, dt)
        for o, w in waived.items():
            o.interest_waived = w
            o.settled_early = True
        sim.cycle_pay_net += amount
        sim.emit(dt, "PAYMENT_POSTED", f"txn{n}", dict(
            transaction_id=str(tid), amount=amount, channel=row["channel"], effective_date=d,
            payment_context="EARLY_SETTLEMENT", allocations=[dict(component=c, amount=a) for _, c, a in plan]))
        sim.settle_info = dict(date=d, amount=amount)
        sim.details.update(early_settlement_date=d, early_settlement_amount=amount)
        sim.cure_hint = "EARLY_SETTLEMENT"
        sim.close(dt, "EARLY_SETTLEMENT")

    def handle_restructure(self, sim, dt, data):
        """Capitalise overdue interest into principal, supersede unpaid rows, build schedule v2."""
        d = dt.date()
        p, rng = sim.plan, sim.rng
        if sim.closed_date:
            return
        dpd, *_ = fr.compute_dpd(sim.obls, d, sim.tol)
        old = [o for o in sim.obls if o.active and o.remaining() > 0]
        if dpd == 0 or not old:
            return
        cap_interest = sum((o.remaining("INTEREST") for o in old if o.eff_due <= d), ZERO)
        if cap_interest > 0:
            sim.ledger.append(dict(entry_id=sim.new_id("ledger"), account_id=sim.account_id, entry_type="CAPITALIZED_INTEREST",
                                   amount=cap_interest, entry_date=d, posted_at=dt))
            sim.principal_bal += cap_interest
        new_principal = sim.principal_bal
        for o in old:
            o.superseded_on = d
        old_ver = sim.schedule_version
        sim.schedule_version = old_ver + 1
        term = data.get("term") or rng.choice([12, 18, 24, 30, 36])
        rate = Decimal(str(data["rate"])) if "rate" in data else (p.rate * Decimal("0.85")).quantize(Decimal("0.0001"))
        anchor = min(d.day, 28)
        first_due = add_months(d, 1, anchor)
        insts, obls = self._make_obligations(sim, sim.schedule_version, new_principal, rate, term, first_due, anchor, p.method)
        sim.details.update(current_schedule_version=sim.schedule_version, restructured_on=d,
                           restructured_principal=new_principal, maturity_date=obls[-1].due_date,
                           installment_amount=insts[0].amount)
        sim.restructure_info = dict(date=d, principal=new_principal, capitalized_interest=cap_interest, term=term, rate=rate)
        sim.cure_hint = "RESTRUCTURED"
        sim.emit(dt, "ACCOUNT_RESTRUCTURED", "restructured", dict(
            restructured_on=d, outstanding_principal=new_principal, capitalized_interest=cap_interest,
            new_term_months=term, new_annual_markup_rate=rate, dpd_at_restructure=dpd))
        sim.emit(dt + timedelta(seconds=5), "REPAYMENT_SCHEDULE_CHANGED", "schedule-v%d" % sim.schedule_version, dict(
            previous_version=old_ver, new_version=sim.schedule_version, new_installment_amount=insts[0].amount,
            first_due_date=first_due, maturity_date=obls[-1].due_date, reason="RESTRUCTURING"))
        p.disc_mult = 0.85
        if not data.get("no_plan"):
            self.plan_installments(sim, sim.schedule_version)

    def finish(self, sim):
        as_of = sim.as_of
        for o in sim.obls:
            if o.superseded_on:
                status = "SUPERSEDED"
            elif o.settled_early:
                status = "SETTLED_EARLY"
            elif o.remaining() == 0:
                status = "PAID"
            elif o.eff_due < as_of and o.remaining() > sim.tol:
                status = "OVERDUE"
            elif sum(o.paid.values(), ZERO) > 0:
                status = "PARTIALLY_PAID"
            elif o.eff_due <= as_of:
                status = "DUE"
            else:
                status = "SCHEDULED"
            o.status = status
            if o.due_date <= as_of and not (o.superseded_on and o.superseded_on < o.due_date) \
                    and (sim.closed_date is None or o.due_date <= sim.closed_date):
                sim.emit(local_dt(o.due_date, 0, 1), "INSTALLMENT_DUE", f"due-v{o.version}-{o.no}", dict(
                    schedule_version=o.version, installment_no=o.no, due_date=o.due_date, effective_due_date=o.eff_due,
                    principal_due=o.due["PRINCIPAL"], interest_due=o.due["INTEREST"], total_due=o.total_due))


# =============================================================================== credit cards
class CardPlanner:
    def stmt_date(self, sim, c):
        return add_months(self.s1, c - 1, sim.plan.statement_day)

    def setup(self, sim):
        p, pol = sim.plan, sim.pol
        self.s1 = first_statement_date(p.open_date, p.statement_day)
        sim.details = dict(account_id=sim.account_id, credit_limit=p.credit_limit, statement_day=p.statement_day,
                           payment_due_days=pol.card_statement_due_days, min_payment_pct=pol.card_min_pct,
                           min_payment_floor=pol.card_min_floor, monthly_finance_rate=pol.card_monthly_finance_rate,
                           late_fee=pol.card_late_fee, card_tier=p.card_tier, card_status="ACTIVE", restriction_reason=None)
        sim.emit(local_dt(p.open_date, 9), "ACCOUNT_CREATED", "created", dict(
            product_category=p.category, opened_date=p.open_date, currency=sim.cfg.currency,
            credit_limit=p.credit_limit, statement_day=p.statement_day))
        rng = sim.rng
        # behavioural episodes (cycle-indexed): missed / short-paid minimums that are later cured
        self.episodes: dict[int, str] = {}
        self.cures: set[int] = set()
        disc = min(0.995, max(0.05, p.cust.discipline * p.disc_mult))
        n_cycles = 0
        while self.stmt_date(sim, n_cycles + 1) <= sim.as_of:
            n_cycles += 1
        horizon = (p.onset - 2) if p.onset else n_cycles - 2
        if rng.random() < min(0.5, 0.03 + 1.2 * (1 - disc) ** 1.3) and horizon >= 4:
            s, m = rng.randint(2, horizon - 1), rng.choice([1, 1, 2, 2, 3])
            if s + m <= horizon and (p.onset is None or s + m < p.onset - 1):
                kind = rng.choice(["MISS", "SHORT"])
                for c in range(s, s + m):
                    self.episodes[c] = kind
                self.cures.add(s + m)
        self.plan_purchases(sim, p.open_date, self.s1, 1)
        if self.s1 <= sim.as_of:
            sim.push(local_dt(self.s1, 23, 30), "STATEMENT", dict(c=1), PRIO_STATEMENT)

    # ---- purchases -------------------------------------------------------------------------
    def plan_purchases(self, sim, start_excl: date, end_incl: date, c: int):
        p, rng = sim.plan, sim.rng
        days = (end_incl - start_excl).days
        if days <= 0:
            return
        force = p.onset is not None and c <= p.onset
        if not force and rng.random() < 0.08:
            return
        target = float(p.credit_limit) * p.spend_ratio * rng.lognormvariate(0, 0.35) * min(1.0, days / 30)
        if force:
            target = max(target, float(p.credit_limit) * 0.12)
        n = rng.randint(2, 8)
        w = [rng.random() + 0.2 for _ in range(n)]
        for wi in w:
            amt = money(Decimal(str(round(target * wi / sum(w) / 10) * 10)))
            if amt < 200:
                continue
            d = start_excl + timedelta(days=rng.randint(1, days))
            sim.push(sim.rand_time(d, 8, 22), "PURCHASE", dict(amount=amt, c=c))

    def handle_purchase(self, sim, dt, data):
        if sim.closed_date or sim.card_status != "ACTIVE":
            return
        if sim.plan.close_cycle is not None and data["c"] > sim.plan.close_cycle:
            return
        bal = sim.billed + sim.unbilled
        avail = sim.plan.credit_limit - bal
        amt = min(data["amount"], avail)
        if amt < Decimal("200"):
            return
        sim.ledger.append(dict(entry_id=sim.new_id("ledger"), account_id=sim.account_id, entry_type="PURCHASE",
                               amount=amt, entry_date=dt.date(), posted_at=dt))
        sim.unbilled += amt
        sim.cycle_purchases += amt

    # ---- statements ------------------------------------------------------------------------
    def handle_statement(self, sim, dt, data):
        c, pol, p = data["c"], sim.pol, sim.plan
        S = dt.date()
        nxt_s = self.stmt_date(sim, c + 1)
        if nxt_s <= sim.as_of:
            sim.push(local_dt(nxt_s, 23, 30), "STATEMENT", dict(c=c + 1), PRIO_STATEMENT)
        if sim.closed_date:
            return
        prev = sim.last_stmt
        fc = fr.card_finance_charge(prev.billed_at_due or ZERO, pol.card_monthly_finance_rate) if prev else ZERO
        fee = pol.card_late_fee if prev and (prev.own_unmet_at_due or ZERO) > sim.tol else ZERO
        opening, purchases, payments = sim.prev_closing, sim.cycle_purchases, sim.cycle_pay_net
        closing = fr.statement_closing(opening, purchases, fc, fee, payments)
        assert closing == sim.billed + sim.unbilled + fc + fee, (sim.plan.number, closing, sim.billed, sim.unbilled, fc, fee)
        cycle_start = (sim.last_stmt_date + timedelta(days=1)) if sim.last_stmt_date else p.open_date
        sim.last_stmt_date = S
        sim.cycle_purchases = sim.cycle_pay_net = ZERO
        sim.prev_closing = closing
        self.plan_purchases(sim, S, min(nxt_s, sim.as_of), c + 1)
        if closing <= 0:
            sim.billed = sim.unbilled = ZERO
            sim.last_stmt = None
            return
        for typ, amt in (("FINANCE_CHARGE", fc), ("FEE", fee)):
            if amt > 0:
                sim.ledger.append(dict(entry_id=sim.new_id("ledger"), account_id=sim.account_id, entry_type=typ,
                                       amount=amt, entry_date=S, posted_at=dt))
        sim.billed, sim.unbilled = closing, ZERO
        carried = sum((o.remaining("MIN_DUE") for o in sim.obls if o.active), ZERO)
        own = fr.card_own_minimum(closing, carried, pol.card_min_pct, pol.card_min_floor)
        due = S + timedelta(days=pol.card_statement_due_days)
        eff = sim.cal.next_business_day(due)
        sid = uid(sim.ctx.ns, "stmt", p.number, c)
        obl = None
        if own > 0:
            obl = Obligation(oid=sid, kind="CARD_MIN", no=len(sim.statements) + 1, due_date=due, eff_due=eff,
                             due={"MIN_DUE": own})
            sim.obls.append(obl)
        no = len(sim.statements) + 1
        row = dict(statement_id=sid, account_id=sim.account_id, statement_no=no, cycle_start_date=cycle_start,
                   statement_date=S, due_date=due, effective_due_date=eff, opening_balance=opening, purchases_total=purchases,
                   finance_charges=fc, fees=fee, payments_total=payments, closing_balance=closing, own_minimum_due=own,
                   minimum_payment_due=own + carried, own_minimum_paid=ZERO, credit_limit=p.credit_limit, status="OPEN",
                   last_payment_effective_date=None)
        st = CardStmt(row=row, obl=obl, closing=closing, minimum=own + carried)
        sim.statements.append(st)
        sim.last_stmt = st
        sim.marks[eff].append(st)
        sim.emit(dt, "CARD_STATEMENT_GENERATED", f"stmt{no}", dict(
            statement_id=str(sid), statement_no=no, statement_date=S, due_date=due, closing_balance=closing,
            minimum_payment_due=own + carried, purchases_total=purchases, finance_charges=fc, fees=fee,
            payments_total=payments, credit_limit=p.credit_limit))
        self.plan_card_payments(sim, c, st, nxt_s)

    # ---- card payment behaviour -------------------------------------------------------------
    def plan_card_payments(self, sim, c, st: CardStmt, nxt_s: date):
        rng, p, as_of = sim.rng, sim.plan, sim.as_of
        S, e = st.row["statement_date"], st.row["effective_due_date"]
        last_ok = min(as_of - timedelta(days=1), nxt_s - timedelta(days=1))
        disc = min(0.995, max(0.05, p.cust.discipline * p.disc_mult))
        mn, closing = st.minimum, st.closing
        if p.close_cycle == c:
            d = min(e, as_of)
            if d > S + timedelta(days=1):
                sim.schedule_payment(sim.rand_time(d - timedelta(days=rng.randint(0, 3))), ("BILLED",), deadline=as_of)
                sim.push(sim.rand_time(min(as_of, d + timedelta(days=3)), 10, 16), "CLOSE", {})
            return
        if p.onset is not None and c >= p.onset:
            self._tail(sim, st, e, last_ok)
            return
        ep = self.episodes.get(c)
        if ep == "MISS":
            return
        if ep == "SHORT":
            amt = money(mn * Decimal(str(round(rng.uniform(0.3, 0.8), 2))))
            if e <= as_of and amt > 0:
                sim.schedule_payment(sim.rand_time(e - timedelta(days=rng.randint(0, 3))), ("FIXED", amt), deadline=e)
            return
        if c in self.cures and e <= as_of:
            sim.schedule_payment(sim.rand_time(e), ("DUE_TO_DATE",), deadline=e + timedelta(days=1), allow_delay=False,
                                 context="POST_COLLECTION_FOLLOWUP")
            return
        mode = rng.choices(["full", "partial", "min"], {
            "TRANSACTOR": [90, 7, 3], "MIXED": [30, 40, 30], "REVOLVER": [8, 32, 60]}[p.card_type])[0]
        if mode == "full":
            rule = ("BILLED",)
        elif mode == "partial":
            frac = Decimal(str(round(rng.uniform(0.15, 0.7), 2)))
            rule = ("FIXED", min(closing, max(mn, _ceil_to(money(closing * frac), 100))))
        else:
            rule = ("FIXED", min(closing, _ceil_to(mn, 100) if rng.random() < 0.5 else mn))
        p_late = 0.02 + 0.35 * (1 - disc) ** 1.5
        room = (last_ok - e).days
        if room >= 1 and rng.random() < p_late:
            d = e + timedelta(days=rng.randint(1, min(room, 14)))
            sim.schedule_payment(sim.rand_time(d), rule, deadline=last_ok,
                                 context="POST_COLLECTION_FOLLOWUP" if (d - e).days >= 10 else "REGULAR")
            return
        d = e - timedelta(days=min(int(rng.expovariate(1 / 4)), max(0, (e - S).days - 2)))
        if d > as_of:                   # statement not yet due at the reference date
            if rng.random() < 0.4 and S + timedelta(days=2) <= as_of:
                d = S + timedelta(days=rng.randint(2, (as_of - S).days))
            else:
                return
        if d == as_of and e >= as_of and rng.random() < 0.35:
            sim.schedule_payment(sim.rand_time(d, 8, 20), ("FIXED", closing if rule[0] != "FIXED" else rule[1]), outcome="PENDING")
            return
        if rng.random() < 0.012 and e <= as_of - timedelta(days=3) and rule[0] == "FIXED":
            sim.schedule_payment(sim.rand_time(d), rule, outcome="FAIL", failure_reason="INSUFFICIENT_FUNDS")
            d = min(e, d + timedelta(days=rng.randint(1, 2)))
        rev = None
        if rng.random() < 0.005 and e <= as_of - timedelta(days=10) and rule[0] == "FIXED":
            k = rng.randint(1, 4)
            repay = d + timedelta(days=k + rng.randint(1, 5))
            if repay <= last_ok:
                rev = dict(after_days=k, reason=rng.choice(["CHEQUE_RETURNED", "IBFT_RETURN"]))
                sim.schedule_payment(sim.rand_time(repay), rule, deadline=last_ok)
        sim.schedule_payment(sim.rand_time(d), rule, reversal=rev, deadline=e if rev is None else d + timedelta(days=1),
                             allow_delay=rev is None)

    def _tail(self, sim, st: CardStmt, e: date, last_ok: date):
        rng = sim.rng
        if sim.tail_budget is None:
            sim.tail_budget = money(st.obl.due["MIN_DUE"] * Decimal("0.8")) if st.obl else ZERO
            if rng.random() < 0.25 and e <= sim.as_of - timedelta(days=1) and st.minimum > 0:
                sim.schedule_payment(sim.rand_time(e), ("FIXED", st.minimum), outcome="FAIL", failure_reason="INSUFFICIENT_FUNDS")
        if rng.random() < 0.3 and last_ok >= e + timedelta(days=1) and sim.tail_budget > 300:
            amt = money(sim.tail_budget * Decimal(str(round(rng.uniform(0.15, 0.4), 2))))
            if amt >= 100:
                sim.tail_budget -= amt
                sim.schedule_payment(sim.rand_time(e + timedelta(days=rng.randint(1, (last_ok - e).days))), ("FIXED", amt),
                                     context="POST_COLLECTION_FOLLOWUP", deadline=last_ok)

    # ---- handlers --------------------------------------------------------------------------
    def handle_pay(self, sim, dt, data):
        sim.on_pay(dt, data)

    def handle_reverse(self, sim, dt, data):
        sim.on_reverse(dt, data)

    def handle_close(self, sim, dt, data):
        if not sim.closed_date and sim.billed + sim.unbilled == 0:
            sim.close(dt, "CUSTOMER_REQUEST")

    def finish(self, sim):
        as_of = sim.as_of
        for st in sim.statements:
            row, ob = st.row, st.obl
            if ob is not None:
                row["own_minimum_paid"] = ob.paid["MIN_DUE"]
                row["last_payment_effective_date"] = ob.last_payment_effective_date()
                row["status"] = "PAID" if ob.remaining() <= sim.tol else ("OVERDUE" if ob.eff_due < as_of else "OPEN")
            else:
                row["status"] = "PAID"
        sim.details["card_status"] = "CLOSED" if sim.closed_date else sim.card_status
        sim.details["restriction_reason"] = None if sim.closed_date else sim.restriction_reason
