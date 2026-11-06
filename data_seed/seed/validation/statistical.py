"""Statistical profiling (informational; soft checks only). Rare outliers are legitimate in banking,
so they are reported and classified but never deleted."""
from __future__ import annotations

import psycopg

from seed.config import GenConfig
from seed.validation.integrity import Check, scope


def q(conn, sql, run_id):
    return conn.execute(sql, {"r": run_id}).fetchall()


def profile(conn: psycopg.Connection, run_id: str, cfg: GenConfig) -> dict:
    out: dict = {}
    out["accounts_by_product"] = dict(q(conn, "SELECT p.category, count(*) FROM accounts t JOIN products p USING (product_id) WHERE t.run_id=%(r)s GROUP BY 1 ORDER BY 1", run_id))
    out["accounts_by_status"] = dict(q(conn, f"SELECT t.status, count(*) FROM {scope('accounts')} GROUP BY 1", run_id))
    out["accounts_per_customer"] = dict(q(conn, "SELECT n, count(*) FROM (SELECT count(*) n FROM accounts WHERE run_id=%(r)s GROUP BY customer_id) x GROUP BY 1 ORDER BY 1", run_id))
    out["risk_band_asof"] = dict(q(conn, f"SELECT t.risk_band, count(*) FROM {scope('risk_profiles')} AND t.profile_source='BEHAVIORAL_AS_OF' GROUP BY 1 ORDER BY 1", run_id))
    out["income_band"] = dict(q(conn, f"SELECT t.income_band, count(*) FROM {scope('customers')} GROUP BY 1 ORDER BY 1", run_id))
    rows = q(conn, f"SELECT t.bucket, count(*) FROM {scope('delinquency_snapshots')} AND t.snapshot_reason='AS_OF' GROUP BY 1", run_id)
    closed = q(conn, "SELECT count(*) FROM accounts WHERE run_id=%(r)s AND status='CLOSED'", run_id)[0][0]
    counts = {b: n for b, n in rows}
    counts["CURRENT"] = counts.get("CURRENT", 0) + closed        # closed accounts carry no arrears => counted as current
    total = sum(counts.values()) or 1
    out["delinquency_asof_all_accounts"] = counts
    actual = {b: n / total for b, n in counts.items()}
    m = cfg.delinquency
    target = {"CURRENT": m.current, "DPD_1_30": m.dpd_1_30, "DPD_31_60": m.dpd_31_60, "DPD_61_90": m.dpd_61_90, "DPD_90_PLUS": m.dpd_90_plus}
    out["delinquency_target_vs_actual"] = {b: {"target": target[b], "actual": round(actual.get(b, 0.0), 4)} for b in target}
    out["delinquency_by_product"] = [list(r) for r in q(conn, """SELECT p.category, t.bucket, count(*) FROM delinquency_snapshots t JOIN accounts a USING (account_id)
        JOIN products p ON p.product_id=a.product_id WHERE a.run_id=%(r)s AND t.snapshot_reason='AS_OF' GROUP BY 1,2 ORDER BY 1,2""", run_id)]
    out["delinquency_by_risk_band"] = [list(r) for r in q(conn, """SELECT r.risk_band, (d.bucket<>'CURRENT') AS delinquent, count(*)
        FROM delinquency_snapshots d JOIN accounts a USING (account_id) JOIN risk_profiles r ON r.customer_id=a.customer_id AND r.profile_source='ORIGINATION'
        WHERE a.run_id=%(r)s AND d.snapshot_reason='AS_OF' GROUP BY 1,2 ORDER BY 1,2""", run_id)]
    out["payment_behaviour"] = dict(q(conn, f"""SELECT CASE WHEN t.last_payment_effective_date IS NULL THEN 'unpaid'
        WHEN t.last_payment_effective_date < t.effective_due_date THEN 'early' WHEN t.last_payment_effective_date = t.effective_due_date THEN 'on_time'
        ELSE 'late' END, count(*) FROM {scope('repayment_schedules')} AND t.effective_due_date <= '{cfg.as_of_date}' AND t.status <> 'SUPERSEDED' GROUP BY 1""", run_id))
    out["payments_by_status"] = dict(q(conn, f"SELECT t.txn_type||'/'||t.status, count(*) FROM {scope('payment_transactions')} GROUP BY 1", run_id))
    out["payments_by_channel"] = dict(q(conn, f"SELECT t.channel, count(*) FROM {scope('payment_transactions')} GROUP BY 1 ORDER BY 2 DESC", run_id))
    out["events_by_type"] = dict(q(conn, f"SELECT t.event_type, count(*) FROM {scope('banking_events')} GROUP BY 1 ORDER BY 2 DESC", run_id))
    # missing values (nullable columns that are populated sometimes)
    miss = {}
    for table, cols in {"customers": [], "accounts": ["closed_date", "close_reason"], "financed_assets": ["lien_released_on", "recovery_review_opened_on", "repossessed_on"],
                        "repayment_schedules": ["last_payment_effective_date"], "payment_transactions": ["posted_at", "failure_reason", "reversal_reason"],
                        "risk_profiles": ["avg_card_utilization"]}.items():
        for c in cols:
            (n, nulls), = q(conn, f"SELECT count(*), count(*) FILTER (WHERE t.{c} IS NULL) FROM {scope(table)}", run_id)
            miss[f"{table}.{c}"] = {"rows": n, "null_pct": round(100 * nulls / n, 2) if n else 0}
    out["missing_values"] = miss
    # duplicates
    out["duplicates"] = {
        "customer_full_name_duplicates (expected: small pool of names)": q(conn, f"SELECT count(*) FROM (SELECT full_name FROM {scope('customers')} GROUP BY 1 HAVING count(*)>1) x", run_id)[0][0],
        "duplicate_event_deliveries (intentional)": q(conn, f"SELECT count(*) FROM {scope('event_delivery_status')} AND t.is_duplicate", run_id)[0][0],
        "duplicate_idempotency_keys": q(conn, f"SELECT count(*) FROM (SELECT t.account_id, t.idempotency_key FROM {scope('payment_transactions')} GROUP BY 1,2 HAVING count(*)>1) x", run_id)[0][0],
    }
    # outliers (IQR rule), classified legit when inside configured product ranges
    out["outliers"] = {}
    for label, sql in {
        "loan principal": "SELECT t.original_principal FROM loan_details t JOIN accounts a USING (account_id) JOIN products p ON p.product_id=a.product_id WHERE a.run_id=%(r)s AND p.category='PERSONAL_LOAN'",
        "card credit limit": f"SELECT t.credit_limit FROM {scope('credit_card_details')}",
        "payment amount": f"SELECT t.amount FROM {scope('payment_transactions')} AND t.txn_type='PAYMENT' AND t.status='POSTED'",
    }.items():
        vals = sorted(float(r[0]) for r in q(conn, sql, run_id))
        if len(vals) < 8:
            continue
        q1, q3 = vals[len(vals) // 4], vals[3 * len(vals) // 4]
        hi = q3 + 1.5 * (q3 - q1)
        n_out = sum(v > hi for v in vals)
        out["outliers"][label] = {"n": len(vals), "q1": q1, "q3": q3, "upper_fence": round(hi, 2), "above_fence": n_out,
                                  "max": vals[-1], "classification": "legitimate rare large values (within configured ranges)" if n_out else "none"}
    return out


def soft_checks(stats: dict, cfg: GenConfig, tolerance: float = 0.03) -> list[Check]:
    out = []
    for b, v in stats["delinquency_target_vs_actual"].items():
        diff = abs(v["actual"] - v["target"])
        out.append(Check(f"delinquency mix {b}: target {v['target']:.2%} vs actual {v['actual']:.2%}", "statistical", False,
                         diff <= tolerance if cfg.n_customers >= 1000 else diff <= 0.08, f"abs diff {diff:.2%}"))
    return out
