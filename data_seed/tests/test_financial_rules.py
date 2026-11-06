"""Unit tests for pure financial rules. Expected numbers are hand-derived (see comments)."""
from datetime import date
from decimal import Decimal

import pytest

from seed.simulation import financial_rules as fr
from seed.simulation.timeline import Calendar, add_months, month_ends_between

D = Decimal


def test_money_rounds_half_up_and_rejects_floats():
    assert fr.money("2.675") == D("2.68")
    assert fr.money("2.674") == D("2.67")
    with pytest.raises(TypeError):
        fr.money(1.5)


def test_reducing_balance_schedule_reconciles():
    # P=100,000, 12% p.a. (i=1%), n=12  ->  EMI = 100000*0.01/(1-1.01^-12) = 8884.88 (standard annuity table value)
    s = fr.build_installments(D("100000"), D("12"), 12, "REDUCING_BALANCE")
    assert len(s) == 12
    assert s[0].amount == D("8884.88")
    assert s[0].interest == D("1000.00") and s[0].principal == D("7884.88")     # 1% of opening principal
    assert sum(i.principal for i in s) == D("100000.00")                          # principal fully repaid
    assert s[-1].opening_principal - s[-1].principal == D("0.00")
    assert abs(s[-1].amount - s[0].amount) < D("0.15")                            # last instalment only absorbs rounding drift
    assert all(i.amount == i.principal + i.interest for i in s)


def test_zero_rate_schedule_is_straight_line_with_residue_in_last():
    s = fr.build_installments(D("100000"), D("0"), 3, "REDUCING_BALANCE")
    assert [i.principal for i in s] == [D("33333.33"), D("33333.33"), D("33333.34")]
    assert all(i.interest == 0 for i in s)


def test_flat_rate_schedule():
    # P=120,000, 18% flat for 24 months => markup = 120000*0.18*2 = 43,200; instalment = (120000+43200)/24 = 6,800
    s = fr.build_installments(D("120000"), D("18"), 24, "FLAT_RATE")
    assert all(i.amount == D("6800.00") for i in s)
    assert sum(i.interest for i in s) == D("43200.00") and sum(i.principal for i in s) == D("120000.00")


def test_flat_rate_rounding_residue_goes_to_last_installment():
    s = fr.build_installments(D("100000"), D("15"), 7, "FLAT_RATE")   # markup 8750.00 / 7 = 1250 exactly; principal /7 not exact
    assert sum(i.principal for i in s) == D("100000.00")
    assert s[0].principal == D("14285.71") and s[-1].principal == D("14285.74")


@pytest.mark.parametrize("dpd,bucket", [(0, "CURRENT"), (1, "DPD_1_30"), (30, "DPD_1_30"), (31, "DPD_31_60"), (60, "DPD_31_60"),
                                         (61, "DPD_61_90"), (90, "DPD_61_90"), (91, "DPD_90_PLUS"), (400, "DPD_90_PLUS")])
def test_bucket_boundaries(dpd, bucket):
    assert fr.bucket_for(dpd) == bucket


def test_grace_days_keep_account_current():
    assert fr.bucket_for(2, grace_days=3) == "CURRENT" and fr.bucket_for(4, grace_days=3) == "DPD_1_30"


def test_card_minimum_rule():
    # 5% of 20,000 = 1,000 (> floor 500)
    assert fr.card_own_minimum(D("20000"), D("0"), D("5"), D("500")) == D("1000.00")
    # 5% of 4,000 = 200 < floor 500
    assert fr.card_own_minimum(D("4000"), D("0"), D("5"), D("500")) == D("500.00")
    # balance below floor: pay the whole balance
    assert fr.card_own_minimum(D("300"), D("0"), D("5"), D("500")) == D("300.00")
    # never exceeds closing balance after carried minimums
    assert fr.card_own_minimum(D("1000"), D("800"), D("5"), D("500")) == D("200.00")


def test_card_finance_charge():
    assert fr.card_finance_charge(D("19400"), D("3.5")) == D("679.00")
    assert fr.card_finance_charge(D("0"), D("3.5")) == D("0.00")
    assert fr.card_finance_charge(D("1000.01"), D("3.5")) == D("35.00")           # 35.00035 -> 35.00


def test_statement_closing_equation():
    assert fr.statement_closing(D("1000"), D("500"), D("35"), D("0"), D("200")) == D("1335")


def _ob(no, due, amt_i, amt_p):
    return fr.Obligation(oid=no, kind="INSTALLMENT", no=no, due_date=due, eff_due=due, due={"INTEREST": D(amt_i), "PRINCIPAL": D(amt_p)})


def test_fifo_allocation_interest_before_principal_oldest_first():
    obs = [_ob(1, date(2026, 1, 5), "100", "900"), _ob(2, date(2026, 2, 5), "100", "900")]
    plan = fr.allocate_fifo(D("1150"), obs)
    assert [(o.no, c, a) for o, c, a in plan] == [(1, "INTEREST", D("100")), (1, "PRINCIPAL", D("900")), (2, "INTEREST", D("100")),
                                                   (2, "PRINCIPAL", D("50"))]
    assert sum(a for *_, a in plan) == D("1150")


def test_dpd_uses_oldest_unmet_and_tolerance():
    obs = [_ob(1, date(2026, 1, 5), "0", "1000"), _ob(2, date(2026, 2, 5), "0", "1000")]
    assert fr.compute_dpd(obs, date(2026, 1, 5), D("1"))[0] == 0               # due today is not yet delinquent
    assert fr.compute_dpd(obs, date(2026, 1, 6), D("1"))[0] == 1
    dpd, over, cnt, oldest = fr.compute_dpd(obs, date(2026, 2, 10), D("1"))
    assert (dpd, over, cnt, oldest) == (36, D("2000"), 2, date(2026, 1, 5))
    obs[0].paid["PRINCIPAL"] = D("999.40")                                     # 0.60 short: within PKR 1 tolerance
    assert fr.compute_dpd(obs, date(2026, 2, 10), D("1"))[0] == 5              # oldest unmet is now instalment 2


def test_add_months_clamps_day_and_calendar_rolls_forward():
    assert add_months(date(2026, 1, 31), 1, 31) == date(2026, 2, 28)
    cal = Calendar([date(2026, 11, 9)])
    assert cal.next_business_day(date(2026, 11, 7)) == date(2026, 11, 10)       # Sat -> skip Sun and Monday holiday
    assert month_ends_between(date(2026, 1, 31), date(2026, 3, 31)) == [date(2026, 2, 28), date(2026, 3, 31)]
