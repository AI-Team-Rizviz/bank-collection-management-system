"""Time-ordered per-account simulation (loans, asset financing, credit cards).

Each account is replayed chronologically from a priority queue of actions (payments, reversals,
statements, purchases, restructuring, early settlement). Ledger, allocations, delinquency (DPD) and
snapshots are DERIVED from the replayed state, never assigned independently.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from seed.config import GenConfig
from seed.simulation import financial_rules as fr
from seed.simulation.financial_rules import ZERO, Obligation, money
from seed.simulation.timeline import Calendar, add_months, local_dt, month_end, month_ends_between, uid

DIGITAL = ("RAAST", "MOBILE_APP", "INTERNET_BANKING", "IBFT", "AUTO_DEBIT")
BRANCH = ("BRANCH_CASH", "CHEQUE")
CHANNEL_WEIGHTS = {"RAAST": 25, "MOBILE_APP": 25, "INTERNET_BANKING": 14, "IBFT": 10, "AUTO_DEBIT": 11, "BRANCH_CASH": 10, "CHEQUE": 5}
PRIO_STATEMENT = 50


@dataclass
class SimContext:
    cfg: GenConfig
    cal: Calendar
    ns: Any   # run namespace UUID


@dataclass
class RawEvent:
    when: datetime
    etype: str
    key: str
    payload: dict
    back_valued: bool = False


@dataclass
class CardStmt:
    row: dict
    obl: Obligation | None
    closing: Decimal
    minimum: Decimal
    billed_at_due: Decimal | None = None
    own_unmet_at_due: Decimal | None = None


class AccountSim:
    def __init__(self, ctx: SimContext, plan, rng):
        self.ctx, self.plan, self.rng = ctx, plan, rng
        self.cfg, self.pol, self.cal = ctx.cfg, ctx.cfg.policy, ctx.cal
        self.as_of: date = ctx.cfg.as_of_date
        self.account_id = uid(ctx.ns, "account", plan.number)
        self.is_card = plan.category == "CREDIT_CARD"
        self.open_date: date = plan.open_date
        self.tol = self.pol.tolerance
        # outputs
        self.txns: list[dict] = []
        self.allocs: list[dict] = []
        self.ledger: list[dict] = []
        self.events: list[RawEvent] = []
        self.dsnaps: dict[tuple, dict] = {}
        self.bsnaps: dict[date, dict] = {}
        self.statements: list[CardStmt] = []
        self.obls: list[Obligation] = []
        # state
        self.heap: list = []
        self.seq = 0
        self.counters: dict[str, int] = defaultdict(int)
        self.clock = self.open_date - timedelta(days=1)
        self.bucket, self.episode_start, self.dpd_now = fr.CURRENT, None, 0
        self.closed_date: date | None = None
        self.close_reason: str | None = None
        self.marks: dict[date, list[CardStmt]] = defaultdict(list)
        self.principal_bal = ZERO
        self.billed = self.unbilled = ZERO
        self.cycle_purchases = self.cycle_pay_net = ZERO
        self.prev_closing = ZERO
        self.last_stmt: CardStmt | None = None
        self.last_stmt_date: date | None = None
        self.card_status = "ACTIVE"
        self.restriction_reason: str | None = None
        self.txn_by_id: dict = {}
        self.txn_allocs: dict = defaultdict(list)
        self.reversed_txns: set = set()
        self.cure_hint: str | None = None
        self.last_payment_id = None
        self.tail_budget: Decimal | None = None
        self.max_dpd_12m = 0
        self.missed_12m = 0
        self.dpd91_date: date | None = None
        self.details: dict = {}          # loan_details / credit_card_details row
        self.restructure_info: dict | None = None
        self.settle_info: dict | None = None
        self.asset_row: dict | None = None
        self.schedule_version = 1

    # ------------------------------------------------------------------ infra
    def new_id(self, kind: str):
        self.counters[kind] += 1
        return uid(self.ctx.ns, "acct", self.plan.number, kind, self.counters[kind])

    def push(self, dt: datetime, kind: str, data: dict, prio: int = 0) -> None:
        if dt.date() > self.as_of:
            return
        self.seq += 1
        heapq.heappush(self.heap, (dt, prio, self.seq, kind, data))

    def emit(self, when: datetime, etype: str, key: str, payload: dict, back_valued: bool = False) -> None:
        self.events.append(RawEvent(when, etype, key, payload, back_valued))

    def rand_time(self, d: date, lo=8, hi=21) -> datetime:
        return local_dt(d, self.rng.randint(lo, hi - 1), self.rng.randint(0, 59), self.rng.randint(0, 59))

    # ------------------------------------------------------------------ outstanding
    def active_obls(self) -> list[Obligation]:
        return [o for o in self.obls if o.active]

    def outstanding_total(self) -> Decimal:
        if self.is_card:
            return self.billed + self.unbilled
        return sum((o.remaining() for o in self.obls if o.active), ZERO)

    # ------------------------------------------------------------------ scheduling payments
    def pick_channel(self, d: date) -> str:
        pool = DIGITAL if not self.cal.is_business_day(d) else tuple(CHANNEL_WEIGHTS)
        return self.rng.choices(pool, [CHANNEL_WEIGHTS[c] for c in pool])[0]

    def schedule_payment(self, initiated: datetime, rule: tuple, *, outcome="POST", context="REGULAR",
                         reversal: dict | None = None, deadline: date | None = None,
                         failure_reason: str | None = None, allow_delay=True) -> None:
        """Queue a payment. `initiated` is the customer's action time; posting time follows channel rules.

        deadline: latest acceptable posting date (a branch/cheque payment that would post later is
        switched to an instant digital channel so planned behaviour stays consistent).
        """
        d0 = initiated.date()
        if d0 > self.as_of or d0 <= self.open_date:
            return
        deadline = min(deadline or self.as_of, self.as_of)
        ch = self.pick_channel(d0)
        if outcome in ("FAIL", "PENDING"):
            ch = ch if ch in DIGITAL else "MOBILE_APP"
            tid = self.new_id("txn")
            if outcome == "FAIL":
                self._record_failed(tid, initiated, rule, ch, failure_reason or "INSUFFICIENT_FUNDS")
            else:
                self._record_pending(tid, initiated, rule, ch, context)
            return
        posted, delayed = self._posting_time(initiated, ch, allow_delay)
        if posted.date() > deadline:   # would post too late for the planned behaviour -> instant channel
            ch = "RAAST"
            posted, delayed = self._posting_time(initiated, ch, False)
        self.push(posted, "PAY", dict(initiated=initiated, rule=rule, channel=ch, context=context,
                                      reversal=reversal, back_valued=delayed > 0))

    def _posting_time(self, initiated: datetime, ch: str, allow_delay: bool) -> tuple[datetime, int]:
        d0 = initiated.date()
        if ch in BRANCH:
            post_day = self.cal.next_business_day(d0 + timedelta(days=1) if initiated.hour >= 16 else d0)
            if ch == "CHEQUE":
                post_day = self.cal.add_business_days(post_day, self.rng.randint(1, 2))
            if post_day == d0 and 9 <= initiated.hour < 16:
                return initiated + timedelta(minutes=2), 0
            return local_dt(post_day, 9, self.rng.randint(30, 59), self.rng.randint(0, 59)), 0
        if allow_delay and ch in ("IBFT", "INTERNET_BANKING") and self.rng.random() < 0.025:
            delayed = self.rng.randint(1, 3)   # back-valued: posted late, value-dated to the initiation date
            return local_dt(self.cal.next_business_day(d0 + timedelta(days=delayed)), 9, self.rng.randint(0, 59), 0), delayed
        return initiated + timedelta(seconds=self.rng.randint(2, 45)), 0

    def _fixed(self, rule) -> Decimal:
        return money(rule[1])

    def _record_failed(self, tid, at, rule, ch, reason) -> None:
        n = self.counters["txn"]
        row = dict(transaction_id=tid, account_id=self.account_id, txn_type="PAYMENT", status="FAILED",
                   amount=self._fixed(rule), currency=self.cfg.currency, channel=ch, initiated_at=at, posted_at=None,
                   effective_date=None, reverses_transaction_id=None, reversal_reason=None, failure_reason=reason,
                   payment_context="REGULAR", idempotency_key=f"{self.plan.number}:PAY:{n:05d}")
        self.txns.append(row)
        self.emit(at + timedelta(seconds=3), "PAYMENT_ATTEMPT_FAILED", f"txn{n}", dict(
            transaction_id=str(tid), amount=row["amount"], channel=ch, failure_reason=reason))

    def _record_pending(self, tid, at, rule, ch, context) -> None:
        n = self.counters["txn"]
        self.txns.append(dict(transaction_id=tid, account_id=self.account_id, txn_type="PAYMENT", status="PENDING",
                              amount=self._fixed(rule), currency=self.cfg.currency, channel=ch, initiated_at=at,
                              posted_at=None, effective_date=None, reverses_transaction_id=None, reversal_reason=None,
                              failure_reason=None, payment_context=context,
                              idempotency_key=f"{self.plan.number}:PAY:{n:05d}"))

    # ------------------------------------------------------------------ amount rules
    def resolve_amount(self, rule: tuple, on: date) -> Decimal:
        kind = rule[0]
        if kind == "FIXED":
            amt = money(rule[1])
        elif kind == "DUE_TO_DATE":     # everything due on/before `on` (incl. overdue)
            amt = sum((o.remaining() for o in self.obls if o.active and o.eff_due <= on), ZERO)
        elif kind == "CLEAR_ALL":
            amt = self.outstanding_total()
        elif kind == "BILLED":
            amt = self.billed
        else:
            raise ValueError(rule)
        return min(amt, self.outstanding_total())

    # ------------------------------------------------------------------ handlers
    def on_pay(self, dt: datetime, data: dict) -> None:
        if self.closed_date:
            return
        init: datetime = data["initiated"]
        amount = self.resolve_amount(data["rule"], init.date())
        if amount < Decimal("0.01"):
            return
        tid = self.new_id("txn")
        n = self.counters["txn"]
        eff = init.date()
        row = dict(transaction_id=tid, account_id=self.account_id, txn_type="PAYMENT", status="POSTED", amount=amount,
                   currency=self.cfg.currency, channel=data["channel"], initiated_at=init, posted_at=dt, effective_date=eff,
                   reverses_transaction_id=None, reversal_reason=None, failure_reason=None, payment_context=data["context"],
                   idempotency_key=f"{self.plan.number}:PAY:{n:05d}")
        self.txns.append(row)
        self.txn_by_id[tid] = row
        plan = self._plan_allocation(amount)
        self._apply_plan(tid, plan, eff, dt)
        self.cycle_pay_net += amount
        self.last_payment_id = tid
        self.emit(dt, "PAYMENT_POSTED", f"txn{n}", dict(
            transaction_id=str(tid), amount=amount, channel=data["channel"], effective_date=eff,
            payment_context=data["context"], allocations=[dict(component=c, amount=a) for _, c, a in plan]),
            back_valued=data.get("back_valued", False))
        rev = data.get("reversal")
        if rev:
            self.push(self.rand_time(dt.date() + timedelta(days=rev["after_days"]), 9, 17), "REVERSE",
                      dict(orig=tid, reason=rev["reason"]))
        self.maybe_close_matured(dt)

    def _plan_allocation(self, amount: Decimal):
        """Returns [(target, component, amount)] where target is an Obligation or None (card unbilled)."""
        if not self.is_card:
            plan = fr.allocate_fifo(amount, [o for o in self.obls if o.active and o.remaining() > 0])
            assert sum(a for *_, a in plan) == amount, "payment exceeds outstanding"
            return plan
        plan, left, billed_left = [], amount, self.billed
        for o in self.obls:
            if o.active and left > 0 and billed_left > 0:
                take = min(left, o.remaining("MIN_DUE"), billed_left)
                if take > 0:
                    plan.append((o, "MIN_DUE", take))
                    left -= take
                    billed_left -= take
        if left > 0 and billed_left > 0:
            take = min(left, billed_left)
            plan.append((self.last_stmt.obl if self.last_stmt and self.last_stmt.obl else None, "BILLED_BALANCE", take))
            left -= take
        if left > 0:
            assert left <= self.unbilled, "card payment exceeds balance"
            plan.append((None, "UNBILLED", left))
        return plan

    def _apply_plan(self, tid, plan, eff: date, dt: datetime) -> None:
        for target, comp, amt in plan:
            if comp in ("INTEREST", "PRINCIPAL"):
                fr.apply_allocation(target, comp, amt, tid, eff)
                if comp == "PRINCIPAL":
                    self.principal_bal -= amt
            elif comp == "MIN_DUE":
                fr.apply_allocation(target, comp, amt, tid, eff)
                self.billed -= amt
            elif comp == "BILLED_BALANCE":
                self.billed -= amt
            else:
                self.unbilled -= amt
            sched = target.oid if target is not None and not self.is_card else None
            stmt = target.oid if target is not None and self.is_card else None
            alloc = dict(allocation_id=self.new_id("alloc"), transaction_id=tid, account_id=self.account_id,
                         allocation_type="APPLY", component=comp, amount=amt, schedule_id=sched, statement_id=stmt)
            self.allocs.append(alloc)
            self.txn_allocs[tid].append((target, comp, amt, alloc))

    def on_reverse(self, dt: datetime, data: dict) -> None:
        orig = data["orig"]
        if self.closed_date or orig in self.reversed_txns or orig not in self.txn_by_id:
            return
        o_row = self.txn_by_id[orig]
        tid = self.new_id("txn")
        n = self.counters["txn"]
        self.reversed_txns.add(orig)
        self.txns.append(dict(
            transaction_id=tid, account_id=self.account_id, txn_type="REVERSAL", status="POSTED", amount=o_row["amount"],
            currency=self.cfg.currency, channel=o_row["channel"], initiated_at=dt, posted_at=dt, effective_date=dt.date(),
            reverses_transaction_id=orig, reversal_reason=data["reason"], failure_reason=None, payment_context="REGULAR",
            idempotency_key=f"{self.plan.number}:REV:{n:05d}"))
        for target, comp, amt, _ in self.txn_allocs[orig]:
            if comp in ("INTEREST", "PRINCIPAL"):
                fr.reverse_allocation(target, comp, amt, orig)
                if comp == "PRINCIPAL":
                    self.principal_bal += amt
            elif comp == "MIN_DUE":
                fr.reverse_allocation(target, comp, amt, orig)
                self.billed += amt
            elif comp == "BILLED_BALANCE":
                self.billed += amt
            else:
                self.unbilled += amt
            self.allocs.append(dict(
                allocation_id=self.new_id("alloc"), transaction_id=tid, account_id=self.account_id,
                allocation_type="REVERSAL", component=comp, amount=amt,
                schedule_id=target.oid if target is not None and not self.is_card else None,
                statement_id=target.oid if target is not None and self.is_card else None))
        self.cycle_pay_net -= o_row["amount"]
        self.emit(dt, "PAYMENT_REVERSED", f"txn{n}", dict(
            transaction_id=str(tid), reverses_transaction_id=str(orig), amount=o_row["amount"], reason=data["reason"]))

    # ------------------------------------------------------------------ closing
    def maybe_close_matured(self, dt: datetime) -> None:
        if self.is_card or self.closed_date:
            return
        act = self.active_obls()
        if act and all(o.remaining() == 0 for o in act):
            self.close(dt, "MATURED" if act[-1].due_date <= dt.date() else "PAID_OFF_EARLY")

    def close(self, dt: datetime, reason: str) -> None:
        self.closed_date, self.close_reason = dt.date(), reason
        self.emit(dt + timedelta(seconds=30), "ACCOUNT_CLOSED", "closed", dict(reason=reason, closed_date=dt.date()))

    # ------------------------------------------------------------------ DPD / snapshots
    def _threshold_dates(self, lo: date, hi: date) -> set[date]:
        ob = fr.oldest_unmet(self.obls, self.tol)
        out = set()
        if ob is None:
            return out
        g = self.pol.grace_days
        for off in (g + 1, 1, 31, 61, 91):
            d = ob.eff_due + timedelta(days=off)
            if lo < d <= hi:
                out.add(d)
        return out

    def catch_up(self, upto: date) -> None:
        if upto <= self.clock:
            return
        dates = self._threshold_dates(self.clock, upto)
        dates |= set(month_ends_between(self.clock, upto))
        dates |= {d for d in self.marks if self.clock < d <= upto}
        if upto == self.as_of:
            dates.add(upto)
        for d in sorted(dates):
            self.finalize_day(d)
        self.clock = upto

    def finalize_day(self, d: date) -> None:
        if d < self.open_date or (self.closed_date and d > self.closed_date):
            return
        tol = self.tol
        dpd, overdue, cnt, oldest = fr.compute_dpd(self.obls, d, tol)
        bucket = fr.bucket_for(dpd, self.pol.grace_days)
        for st in self.marks.pop(d, []):
            st.billed_at_due = self.billed
            st.own_unmet_at_due = st.obl.remaining() if st.obl else ZERO
        if d >= self.as_of - timedelta(days=365):
            self.max_dpd_12m = max(self.max_dpd_12m, dpd)
        if bucket != self.bucket:
            self._transition(d, dpd, bucket, overdue, cnt, oldest)
        self.dpd_now = dpd
        if self.is_card:
            self._card_restrictions(dpd)
        is_me, is_asof = d == month_end(d), d == self.as_of
        if is_me:
            self._delinq_snapshot(d, "MONTH_END", dpd, bucket, overdue, cnt, oldest)
        if is_asof:
            self._delinq_snapshot(d, "AS_OF", dpd, bucket, overdue, cnt, oldest)
        if is_me or is_asof:
            self._balance_snapshot(d, "AS_OF" if is_asof else "MONTH_END", overdue)

    def _transition(self, d, dpd, bucket, overdue, cnt, oldest) -> None:
        prev = self.bucket
        at = local_dt(d, 23, 55)
        info = dict(dpd=dpd, bucket=bucket, previous_bucket=prev, overdue_amount=overdue,
                    overdue_obligation_count=cnt, oldest_unpaid_due_date=oldest)
        if prev == fr.CURRENT:
            self.episode_start = d
            info["delinquency_start_date"] = d
            if d >= self.as_of - timedelta(days=365):
                self.missed_12m += 1
            self.emit(at, "ACCOUNT_DELINQUENT", f"delq-{d}", info)
        elif bucket == fr.CURRENT:
            info["delinquency_start_date"] = self.episode_start
            info["cure_reason"] = self.cure_hint or "PAYMENT"
            info["days_delinquent"] = (d - self.episode_start).days if self.episode_start else None
            self.emit(at, "DELINQUENCY_CURED", f"cure-{d}", info)
            self.episode_start, self.cure_hint, self.dpd91_date = None, None, None
        else:
            info["delinquency_start_date"] = self.episode_start
            self.emit(at, "DELINQUENCY_BUCKET_CHANGED", f"bucket-{d}-{bucket}", info)
        if bucket == "DPD_90_PLUS" and self.dpd91_date is None and oldest:
            self.dpd91_date = oldest + timedelta(days=91)
        self.bucket = bucket
        self._delinq_snapshot(d, "TRANSITION", dpd, bucket, overdue, cnt, oldest)

    def _delinq_snapshot(self, d, reason, dpd, bucket, overdue, cnt, oldest) -> None:
        eligible = dpd >= self.pol.collection_min_dpd and bucket != fr.CURRENT and overdue >= self.pol.collection_min_overdue
        self.dsnaps[(d, reason)] = dict(
            snapshot_id=self.new_id("dsnap") if (d, reason) not in self.dsnaps else self.dsnaps[(d, reason)]["snapshot_id"],
            account_id=self.account_id, snapshot_date=d, snapshot_reason=reason, dpd=dpd, bucket=bucket,
            overdue_amount=overdue, overdue_obligation_count=cnt, oldest_unpaid_due_date=oldest,
            delinquency_start_date=self.episode_start if bucket != fr.CURRENT else None,
            is_collection_eligible=bool(eligible), policy_version=self.pol.policy_version)

    def _balance_snapshot(self, d, kind, overdue) -> None:
        bal = self.billed + self.unbilled if self.is_card else self.principal_bal
        row = dict(snapshot_id=self.bsnaps[d]["snapshot_id"] if d in self.bsnaps else self.new_id("bsnap"),
                   account_id=self.account_id, snapshot_date=d, snapshot_type=kind, outstanding_balance=bal,
                   overdue_amount=overdue, billed_balance=None, unbilled_balance=None, credit_limit=None, available_credit=None)
        if self.is_card:
            lim = self.plan.credit_limit
            row.update(billed_balance=self.billed, unbilled_balance=self.unbilled, credit_limit=lim,
                       available_credit=max(ZERO, lim - bal))
        self.bsnaps[d] = row

    def _card_restrictions(self, dpd: int) -> None:
        if self.closed_date:
            self.card_status, self.restriction_reason = "CLOSED", None
        elif dpd > self.pol.card_suspend_dpd:
            self.card_status, self.restriction_reason = "SUSPENDED", "DPD_OVER_SUSPEND_THRESHOLD"
        elif dpd > self.pol.card_block_dpd:
            self.card_status, self.restriction_reason = "TEMPORARY_BLOCK", "DPD_OVER_BLOCK_THRESHOLD"
        else:
            self.card_status, self.restriction_reason = "ACTIVE", None

    # ------------------------------------------------------------------ main loop
    def run(self, planner) -> "AccountSim":
        planner.setup(self)
        while self.heap:
            dt, _, _, kind, data = heapq.heappop(self.heap)
            d = dt.date()
            if d > self.clock:
                self.catch_up(d - timedelta(days=1))
                if d - timedelta(days=1) >= self.open_date:
                    self._track_max(d - timedelta(days=1))
            getattr(planner, "handle_" + kind.lower())(self, dt, data)
            if not self.heap or self.heap[0][0].date() > d:
                self.finalize_day(d)
                self.clock = d
        self.catch_up(self.as_of)
        planner.finish(self)
        return self

    def _track_max(self, d: date) -> None:
        if d >= self.as_of - timedelta(days=365):
            dpd, *_ = fr.compute_dpd(self.obls, d, self.tol)
            self.max_dpd_12m = max(self.max_dpd_12m, dpd)
