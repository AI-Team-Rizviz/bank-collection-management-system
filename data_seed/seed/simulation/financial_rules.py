"""Pure financial rules (Decimal only). Documented assumptions:

* Currency PKR, 2 decimal places, ROUND_HALF_UP at every monetary computation.
* Reducing balance (personal loans): EMI = P*i / (1-(1+i)^-n), i = annual%/1200, rounded to 0.01.
  interest_k = round(opening_k * i); principal_k = EMI - interest_k; the LAST installment clears
  the remaining principal (absorbs rounding drift): amount_n = opening_n + round(opening_n * i).
* Flat rate (asset financing): total markup = round(P * rate% * n/12), spread evenly; principal is
  spread evenly; the last installment absorbs rounding residue.
* Installment payments are applied oldest-obligation-first; within an installment INTEREST then PRINCIPAL.
* DPD is an end-of-day measure: DPD(d) = d - effective_due_date of the oldest obligation whose
  unpaid amount exceeds the tolerance and whose effective due date is before d (0 otherwise).
  effective_due_date = next business day on/after the contractual due date.
* Cards: minimum = min(closing, max(floor, pct*closing)) (own minimum) + unmet earlier minimums;
  finance charge = monthly_rate% * billed balance still unpaid at the payment due date (zero if the
  statement was cleared by the due date => interest-free grace); late fee if the own minimum was
  not met by the due date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, getcontext
from uuid import UUID

getcontext().prec = 40
ZERO = Decimal("0.00")
CENT = Decimal("0.01")

CURRENT = "CURRENT"
BUCKETS = ("CURRENT", "DPD_1_30", "DPD_31_60", "DPD_61_90", "DPD_90_PLUS")


def money(x) -> Decimal:
    if isinstance(x, float):
        raise TypeError("floats are not allowed for money")
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def bucket_for(dpd: int, grace_days: int = 0) -> str:
    if dpd <= grace_days:
        return CURRENT
    if dpd <= 30:
        return "DPD_1_30"
    if dpd <= 60:
        return "DPD_31_60"
    if dpd <= 90:
        return "DPD_61_90"
    return "DPD_90_PLUS"


BUCKET_RANGES = {"DPD_1_30": (1, 30), "DPD_31_60": (31, 60), "DPD_61_90": (61, 90), "DPD_90_PLUS": (91, 400)}


# --------------------------------------------------------------------------- schedules
@dataclass(frozen=True)
class Installment:
    no: int
    opening_principal: Decimal
    principal: Decimal
    interest: Decimal
    amount: Decimal


def build_installments(principal: Decimal, annual_rate_pct: Decimal, n: int, method: str) -> list[Installment]:
    principal = money(principal)
    rate = Decimal(annual_rate_pct)
    out: list[Installment] = []
    opening = principal
    if method == "REDUCING_BALANCE":
        i = rate / Decimal(1200)
        if i == 0:
            base = money(principal / n)
            emi = base
        else:
            emi = money(principal * i / (1 - (1 + i) ** (-n)))
        for k in range(1, n + 1):
            interest = money(opening * i)
            if k == n:
                princ = opening
            elif i == 0:
                princ = base
            else:
                princ = emi - interest
            out.append(Installment(k, opening, princ, interest, princ + interest))
            opening -= princ
    elif method == "FLAT_RATE":
        total_markup = money(principal * rate / Decimal(100) * Decimal(n) / Decimal(12))
        base_p, base_i = money(principal / n), money(total_markup / n)
        paid_p = paid_i = ZERO
        for k in range(1, n + 1):
            princ = principal - paid_p if k == n else base_p
            interest = total_markup - paid_i if k == n else base_i
            out.append(Installment(k, opening, princ, interest, princ + interest))
            paid_p += princ
            paid_i += interest
            opening -= princ
    else:
        raise ValueError(f"unknown method {method}")
    assert sum(x.principal for x in out) == principal
    return out


# --------------------------------------------------------------------------- obligations
INSTALLMENT_COMPONENTS = ("INTEREST", "PRINCIPAL")
CARD_COMPONENTS = ("MIN_DUE",)


@dataclass(eq=False)
class Obligation:
    """A repayment_schedules row (installment) or the own-minimum part of a card statement."""

    oid: UUID
    kind: str                       # INSTALLMENT | CARD_MIN
    no: int
    due_date: date
    eff_due: date
    due: dict[str, Decimal]
    version: int = 1
    paid: dict[str, Decimal] = field(default_factory=dict)
    status: str = "SCHEDULED"
    superseded_on: date | None = None
    settled_early: bool = False
    interest_waived: Decimal = ZERO
    contribs: dict[UUID, tuple[date, Decimal]] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        for c in self.due:
            self.paid.setdefault(c, ZERO)

    @property
    def active(self) -> bool:
        return self.superseded_on is None and not self.settled_early

    def remaining(self, comp: str | None = None) -> Decimal:
        if comp:
            return self.due[comp] - self.paid[comp]
        return sum((self.due[c] - self.paid[c] for c in self.due), ZERO)

    @property
    def total_due(self) -> Decimal:
        return sum(self.due.values(), ZERO)

    def last_payment_effective_date(self) -> date | None:
        return max((e for e, _ in self.contribs.values()), default=None)


def allocate_fifo(amount: Decimal, obligations: list[Obligation], components=INSTALLMENT_COMPONENTS):
    """Oldest-first allocation plan [(obligation, component, amount)]; does not mutate."""
    left, plan = amount, []
    for ob in obligations:
        for comp in components:
            if left <= 0:
                return plan
            take = min(left, ob.remaining(comp))
            if take > 0:
                plan.append((ob, comp, take))
                left -= take
    return plan


def apply_allocation(ob: Obligation, comp: str, amt: Decimal, txn_id: UUID, eff: date) -> None:
    ob.paid[comp] += amt
    prev = ob.contribs.get(txn_id, (eff, ZERO))
    ob.contribs[txn_id] = (eff, prev[1] + amt)


def reverse_allocation(ob: Obligation, comp: str, amt: Decimal, txn_id: UUID) -> None:
    ob.paid[comp] -= amt
    eff, a = ob.contribs[txn_id]
    if a - amt <= 0:
        del ob.contribs[txn_id]
    else:
        ob.contribs[txn_id] = (eff, a - amt)


def oldest_unmet(obligations: list[Obligation], tolerance: Decimal) -> Obligation | None:
    for ob in obligations:
        if ob.active and ob.remaining() > tolerance:
            return ob
    return None


def compute_dpd(obligations: list[Obligation], on: date, tolerance: Decimal) -> tuple[int, Decimal, int, date | None]:
    """(dpd, overdue_amount, overdue_obligation_count, oldest_unpaid_due) at end of day `on`."""
    ob = oldest_unmet(obligations, tolerance)
    if ob is None or ob.eff_due >= on:
        return 0, ZERO, 0, None
    amount, count = ZERO, 0
    for o in obligations:
        if o.active and o.eff_due < on and o.remaining() > tolerance:
            amount += o.remaining()
            count += 1
    return (on - ob.eff_due).days, amount, count, ob.eff_due


# --------------------------------------------------------------------------- credit card
def card_own_minimum(closing: Decimal, carried_unmet: Decimal, pct: Decimal, floor: Decimal) -> Decimal:
    if closing <= 0:
        return ZERO
    own = max(floor, money(closing * pct / Decimal(100)))
    return max(ZERO, min(own, closing - carried_unmet))


def card_finance_charge(unpaid_billed_at_due: Decimal, monthly_rate_pct: Decimal) -> Decimal:
    if unpaid_billed_at_due <= 0:
        return ZERO
    return money(unpaid_billed_at_due * monthly_rate_pct / Decimal(100))


def statement_closing(opening: Decimal, purchases: Decimal, finance: Decimal, fees: Decimal, payments_net: Decimal) -> Decimal:
    return opening + purchases + finance + fees - payments_net
