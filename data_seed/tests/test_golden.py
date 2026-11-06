"""Golden scenarios: small, human-readable, hand-calculated expectations asserted against the engine.

Contract used everywhere: loan PKR 120,000, 12 months, 0% markup => instalment PKR 10,000, opened 2026-07-05, so
due dates are Aug 5 (Wed), Sep 5 (Sat -> effective Mon Sep 7), Oct 5 (Mon), Nov 5 (Thu).  DPD is end-of-day.
"""
from datetime import date
from decimal import Decimal

from seed.generators.events import build_event_rows
from tests.conftest import at, dpd_on, make_card, make_cfg, make_loan

D = Decimal
OPEN = date(2026, 7, 5)


def loan(as_of, **kw):
    return make_loan(OPEN, "120000", 12, as_of, **kw)


def asof(sim, d):
    row = dpd_on(sim, d, "AS_OF")
    assert row is not None, "AS_OF snapshot missing"
    return row


def test_01_paid_on_time_dpd_zero():
    sim = loan(date(2026, 8, 6), payments=[(at(2026, 8, 5), "10000")])
    row = asof(sim, date(2026, 8, 6))
    assert (row["dpd"], row["overdue_amount"], row["bucket"]) == (0, D("0"), "CURRENT")
    assert not [e for e in sim.events if e.etype == "ACCOUNT_DELINQUENT"]


def test_02_overdue_by_one_day():
    sim = loan(date(2026, 8, 6))
    row = asof(sim, date(2026, 8, 6))
    assert (row["dpd"], row["overdue_amount"], row["bucket"], row["delinquency_start_date"]) == (1, D("10000"), "DPD_1_30", date(2026, 8, 6))
    assert row["is_collection_eligible"] is True


def test_03_three_unpaid_installments():
    # Aug 5, Sep 7(eff), Oct 5 unpaid; DPD(Oct 6) = Oct 6 - Aug 5 = 62 days
    sim = loan(date(2026, 10, 6))
    row = asof(sim, date(2026, 10, 6))
    assert (row["dpd"], row["overdue_amount"], row["overdue_obligation_count"], row["bucket"]) == (62, D("30000"), 3, "DPD_61_90")
    # bucket transitions happened on the exact threshold days: Aug 6 (1), Sep 5 (31), Oct 5 (61)
    changes = sorted((r["snapshot_date"], r["bucket"]) for (d, reason), r in sim.dsnaps.items() if reason == "TRANSITION")
    assert changes == [(date(2026, 8, 6), "DPD_1_30"), (date(2026, 9, 5), "DPD_31_60"), (date(2026, 10, 5), "DPD_61_90")]


def test_04_partial_payment_reduces_arrears_fifo():
    # PKR 15,000 on Sep 20: clears Aug (10,000) and 5,000 of Sep. Oct 6: Sep remaining 5,000 + Oct 10,000 overdue.
    sim = loan(date(2026, 10, 6), payments=[(at(2026, 9, 20), "15000")])
    row = asof(sim, date(2026, 10, 6))
    assert (row["dpd"], row["overdue_amount"], row["overdue_obligation_count"]) == (29, D("15000"), 2)   # Oct 6 - Sep 7
    assert row["oldest_unpaid_due_date"] == date(2026, 9, 7)


def test_05_full_arrears_payment_returns_to_current():
    # Customer misses Aug-Oct, pays PKR 40,000 on Nov 5 (the 4th instalment falls due the same day).
    sim = loan(date(2026, 11, 6), payments=[(at(2026, 11, 5), "40000")])
    assert asof(sim, date(2026, 11, 6))["dpd"] == 0
    cured = [e for e in sim.events if e.etype == "DELINQUENCY_CURED"]
    assert [e.when.date() for e in cured] == [date(2026, 11, 5)] and cured[0].payload["previous_bucket"] == "DPD_90_PLUS"
    assert cured[0].payload["delinquency_start_date"] == date(2026, 8, 6)
    # the day before the cure the account was 91 days past due (Aug 5 -> Nov 4)
    assert max(r["dpd"] for r in sim.dsnaps.values()) == 91
    assert sim.max_dpd_12m == 91


def test_06_card_below_minimum_delinquency_persists():
    # opened Jun 20, statement day 20: purchase 20,000 -> statement Jul 20: closing 20,000, minimum max(500, 5%) = 1,000, due Aug 10.
    sim = make_card(date(2026, 6, 20), date(2026, 8, 11), purchases=[(at(2026, 7, 10), "20000")], payments=[(at(2026, 8, 8), "600")])
    st = sim.statements[0].row
    assert (st["closing_balance"], st["minimum_payment_due"], st["due_date"]) == (D("20000"), D("1000"), date(2026, 8, 10))
    row = asof(sim, date(2026, 8, 11))
    assert (row["dpd"], row["overdue_amount"], row["bucket"]) == (1, D("400"), "DPD_1_30")
    # statement distinct from revolving balance: balance owed (19,400) far exceeds the 400 overdue minimum
    assert sim.billed == D("19400")


def test_06b_card_next_statement_charges_and_late_fee():
    sim = make_card(date(2026, 6, 20), date(2026, 8, 21), purchases=[(at(2026, 7, 10), "20000")], payments=[(at(2026, 8, 8), "600")])
    s2 = sim.statements[1].row
    # finance charge 3.5% x 19,400 unpaid at due date = 679.00; late fee 1,500; closing = 20,000 + 679 + 1,500 - 600
    assert (s2["finance_charges"], s2["fees"], s2["payments_total"], s2["closing_balance"]) == (D("679.00"), D("1500.00"), D("600"), D("21579.00"))
    assert s2["own_minimum_due"] == D("1078.95") and s2["minimum_payment_due"] == D("1478.95")   # 5% of 21,579 + 400 carried


def test_07_card_minimum_satisfied_no_delinquency_but_revolving_charge():
    sim = make_card(date(2026, 6, 20), date(2026, 8, 21), purchases=[(at(2026, 7, 10), "20000")], payments=[(at(2026, 8, 8), "1000")])
    assert asof(sim, date(2026, 8, 21))["dpd"] == 0
    s2 = sim.statements[1].row
    assert (s2["finance_charges"], s2["fees"], s2["closing_balance"]) == (D("665.00"), D("0"), D("19665.00"))   # 3.5% x 19,000
    assert s2["own_minimum_due"] == D("983.25")


def test_08_payment_reversal_restores_delinquency():
    sim = loan(date(2026, 8, 10), payments=[(at(2026, 8, 5), "10000")], reversals=[(at(2026, 8, 8), 1)])
    row = asof(sim, date(2026, 8, 10))
    assert (row["dpd"], row["overdue_amount"]) == (5, D("10000"))                     # Aug 10 - Aug 5
    started = [e for e in sim.events if e.etype == "ACCOUNT_DELINQUENT"]
    assert [e.when.date() for e in started] == [date(2026, 8, 8)] and started[0].payload["dpd"] == 3
    # money neither created nor lost: principal balance back to the full 120,000
    assert sim.principal_bal == D("120000")


def test_09_duplicate_delivery_does_not_duplicate_financial_postings():
    sim = loan(date(2026, 8, 6), payments=[(at(2026, 8, 5), "10000")])
    cfg = make_cfg(date(2026, 8, 6), duplicate_delivery_rate=1.0, delayed_delivery_rate=0.0)
    events, deliveries = build_event_rows(cfg, sim.ctx.ns, sim, sim.account_id)
    posted_events = [e for e in events if e["event_type"] == "PAYMENT_POSTED"]
    posted_txns = [t for t in sim.txns if t["status"] == "POSTED" and t["txn_type"] == "PAYMENT"]
    assert len(posted_events) == len(posted_txns) == 1                              # one logical posting
    assert len(deliveries) == 2 * len(events)                                       # every event delivered twice ...
    assert {d["event_id"] for d in deliveries} == {e["event_id"] for e in events}   # ... under the SAME event_id
    assert sum(d["is_duplicate"] for d in deliveries) == len(events)
    assert len({e["event_id"] for e in events}) == len(events)                      # stable, unique ids


def test_10_restructuring_applies_new_schedule():
    sim = make_loan(date(2026, 1, 5), "120000", 12, date(2026, 5, 12), restructure=(at(2026, 5, 11), dict(term=24, rate=0, no_plan=True)))
    v1 = [o for o in sim.obls if o.version == 1]
    v2 = [o for o in sim.obls if o.version == 2]
    assert len(v2) == 24 and all(o.total_due == D("5000.00") for o in v2)           # 120,000 / 24
    assert v2[0].due_date == date(2026, 6, 11)
    assert all(o.status == "SUPERSEDED" for o in v1)                                # nothing was paid; all v1 rows superseded
    assert asof(sim, date(2026, 5, 12))["dpd"] == 0 and sim.details["current_schedule_version"] == 2
    kinds = [e.etype for e in sim.events]
    assert "ACCOUNT_RESTRUCTURED" in kinds and "REPAYMENT_SCHEDULE_CHANGED" in kinds
    cured = [e for e in sim.events if e.etype == "DELINQUENCY_CURED"]
    assert cured and cured[0].payload["cure_reason"] == "RESTRUCTURED"


def test_11_multiple_accounts_one_customer_are_independent():
    paid = make_loan(OPEN, "120000", 12, date(2026, 8, 6), number="LOAN-GOLD01", payments=[(at(2026, 8, 5), "10000")])
    unpaid = make_loan(OPEN, "120000", 12, date(2026, 8, 6), number="LOAN-GOLD02")
    assert asof(paid, date(2026, 8, 6))["dpd"] == 0
    assert asof(unpaid, date(2026, 8, 6))["dpd"] == 1


def test_12_late_posted_payment_keeps_value_date():
    # initiated on the due date (Aug 5) but posted two days later; value-dated Aug 5.
    sim = loan(date(2026, 8, 7), payments=[(at(2026, 8, 5), "10000", at(2026, 8, 7, 9, 30))])
    # delinquent as known at Aug 6 EOD (not yet posted), cured on the Aug 7 posting
    assert [r["dpd"] for (d, reason), r in sorted(sim.dsnaps.items()) if reason == "TRANSITION"] == [1, 0]
    assert asof(sim, date(2026, 8, 7))["dpd"] == 0
    first = sim.obls[0]
    assert first.last_payment_effective_date() == date(2026, 8, 5)                  # cleared ON the due date by effective date
    posted = [t for t in sim.txns if t["status"] == "POSTED"][0]
    assert posted["effective_date"] == date(2026, 8, 5) and posted["posted_at"].date() == date(2026, 8, 7)


def test_weekend_due_date_rolls_to_next_business_day():
    sim = loan(date(2026, 9, 8), payments=[(at(2026, 8, 5), "10000")])
    sep = sim.obls[1]
    assert (sep.due_date, sep.eff_due) == (date(2026, 9, 5), date(2026, 9, 7))      # Sat -> Mon
    assert asof(sim, date(2026, 9, 8))["dpd"] == 1                                  # delinquent from Sep 8, not Sep 6
