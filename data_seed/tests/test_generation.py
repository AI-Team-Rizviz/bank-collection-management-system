"""In-memory data tests (no database): relationships, consistency, determinism."""
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal

import pytest

from seed.config import load_config
from seed.generators.portfolio import generate_chunks

D = Decimal


def build(**kw):
    cfg = load_config(profile="custom", customers=60, **kw)
    tables = defaultdict(list)
    for _, rows in generate_chunks(cfg):
        for t, r in rows.items():
            tables[t].extend(r)
    return cfg, tables


@pytest.fixture(scope="module")
def data():
    return build(seed=11)


def digest(tables):
    blob = json.dumps({t: sorted(json.dumps(r, default=str, sort_keys=True) for r in rows) for t, rows in sorted(tables.items())})
    return hashlib.sha256(blob.encode()).hexdigest()


def test_deterministic_for_same_seed_and_different_for_other_seed(data):
    assert digest(build(seed=11)[1]) == digest(data[1])
    assert digest(build(seed=12)[1]) != digest(data[1])


def test_output_is_independent_of_chunk_size(data):
    assert digest(build(seed=11, chunk_customers=7)[1]) == digest(data[1])


def test_referential_relationships(data):
    _, t = data
    cust = {c["customer_id"] for c in t["customers"]}
    acct = {a["account_id"]: a for a in t["accounts"]}
    assert all(a["customer_id"] in cust for a in acct.values())
    for table in ("repayment_schedules", "card_statements", "payment_transactions", "payment_allocations", "banking_events",
                  "delinquency_snapshots", "account_balance_snapshots", "ledger_entries"):
        assert all(r["account_id"] in acct for r in t[table]), table
    assert len(t["loan_details"]) + len(t["credit_card_details"]) == len(acct)
    assert len(t["financed_assets"]) == sum(1 for a in t["accounts"] if a["account_number"].startswith("ASSET"))
    assert {e["event_id"] for e in t["banking_events"]} >= {d["event_id"] for d in t["event_delivery_status"]}
    assert len({c["customer_id"] for c in t["risk_profiles"]}) == len(cust)          # every customer is risk-profiled


def test_payments_allocations_and_reversals_are_consistent(data):
    _, t = data
    tx = {x["transaction_id"]: x for x in t["payment_transactions"]}
    applied, reversed_ = defaultdict(D), defaultdict(D)
    for a in t["payment_allocations"]:
        assert a["amount"] > 0
        assert tx[a["transaction_id"]]["status"] == "POSTED"
        (applied if a["allocation_type"] == "APPLY" else reversed_)[a["transaction_id"]] += a["amount"]
    for x in tx.values():
        assert x["amount"] > 0
        if x["txn_type"] == "PAYMENT" and x["status"] == "POSTED":
            assert applied[x["transaction_id"]] == x["amount"]
        elif x["txn_type"] == "REVERSAL":
            orig = tx[x["reverses_transaction_id"]]
            assert orig["status"] == "POSTED" and orig["amount"] == x["amount"] == reversed_[x["transaction_id"]]
            assert orig["posted_at"] <= x["posted_at"] and orig["account_id"] == x["account_id"]
        else:
            assert x["transaction_id"] not in applied                                  # failed / pending: no money moved
    assert max(Counter(x["reverses_transaction_id"] for x in tx.values() if x["reverses_transaction_id"]).values(), default=1) == 1


def test_schedule_and_statement_arithmetic(data):
    _, t = data
    by_acct = defaultdict(list)
    for s in t["repayment_schedules"]:
        assert s["total_due"] == s["principal_due"] + s["interest_due"]
        assert s["principal_paid"] <= s["principal_due"]
        by_acct[(s["account_id"], s["schedule_version"])].append(s)
    ld = {l["account_id"]: l for l in t["loan_details"]}
    for (acct, ver), rows in by_acct.items():
        if ver == 1:
            assert sum(r["principal_due"] for r in rows) == ld[acct]["original_principal"]
    for s in t["card_statements"]:
        assert s["closing_balance"] == s["opening_balance"] + s["purchases_total"] + s["finance_charges"] + s["fees"] - s["payments_total"]
        assert s["own_minimum_due"] <= s["minimum_payment_due"] <= s["closing_balance"]


def test_events_are_time_consistent_and_stable(data):
    _, t = data
    ids = [e["event_id"] for e in t["banking_events"]]
    assert len(ids) == len(set(ids))
    assert all(e["recorded_at"] >= e["occurred_at"] for e in t["banking_events"])
    acct_open = {a["account_id"]: a["opened_date"] for a in t["accounts"]}
    assert all(e["occurred_at"].date() >= acct_open[e["account_id"]] for e in t["banking_events"])
    seq = defaultdict(list)
    for e in sorted(t["banking_events"], key=lambda e: e["account_sequence"]):
        seq[e["account_id"]].append(e["occurred_at"])
    assert all(v == sorted(v) for v in seq.values())                                    # business order preserved per account
    dup = Counter(d["event_id"] for d in t["event_delivery_status"])
    assert any(n > 1 for n in dup.values()) or len(t["event_delivery_status"]) < 200   # duplicates reuse event_id


def test_no_real_identifiers(data):
    _, t = data
    for c in t["customers"]:
        assert c["email_placeholder"].endswith("@example.invalid") and c["phone_placeholder"].startswith("+92-000-")
        assert c["national_id_token"].startswith("SYN-ID-")


def test_delinquency_is_derived_from_obligations(data):
    """Every account in a delinquent bucket at as_of has a genuinely unpaid, past-due obligation."""
    cfg, t = data
    snaps = {s["account_id"]: s for s in t["delinquency_snapshots"] if s["snapshot_reason"] == "AS_OF"}
    unpaid = defaultdict(list)
    for s in t["repayment_schedules"]:
        if s["status"] == "OVERDUE":
            unpaid[s["account_id"]].append(s["effective_due_date"])
    for s in t["card_statements"]:
        if s["status"] == "OVERDUE":
            unpaid[s["account_id"]].append(s["effective_due_date"])
    for acct, snap in snaps.items():
        if snap["bucket"] != "CURRENT":
            assert unpaid[acct], acct
            assert snap["dpd"] == (cfg.as_of_date - min(unpaid[acct])).days
        else:
            assert not unpaid[acct]
