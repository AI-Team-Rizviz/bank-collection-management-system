"""Run all validations, compute scenario coverage and write the quality report (JSON + Markdown)."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from seed.config import PROJECT_ROOT, GenConfig
from seed.validation import financial, integrity, statistical, temporal
from seed.validation.integrity import Check, scope

SCENARIOS = {  # name -> SQL returning a count (must be > 0 for coverage)
    "on-time installment payment": "SELECT count(*) FROM {rs} AND t.last_payment_effective_date = t.effective_due_date",
    "early installment payment": "SELECT count(*) FROM {rs} AND t.last_payment_effective_date < t.effective_due_date",
    "late installment payment (cleared after due date)": "SELECT count(*) FROM {rs} AND t.last_payment_effective_date > t.effective_due_date AND t.status='PAID'",
    "partial installment payment (still overdue)": "SELECT count(*) FROM {rs} AND t.status='OVERDUE' AND t.principal_paid+t.interest_paid>0",
    "multiple consecutive missed installments (>=3 overdue at snapshot)": "SELECT count(*) FROM {ds} AND t.overdue_obligation_count>=3",
    "card statement cleared in full by next cycle": "SELECT count(*) FROM {cs} AND t.statement_no>1 AND t.payments_total >= t.opening_balance AND t.opening_balance>0",
    "card minimum-only style payment (revolving, finance charge applied)": "SELECT count(*) FROM {cs} AND t.finance_charges>0",
    "card minimum not satisfied (insufficient payment)": "SELECT count(*) FROM {cs} AND t.status='OVERDUE'",
    "card late fee assessed": "SELECT count(*) FROM {cs} AND t.fees>0",
    "delinquency started (ACCOUNT_DELINQUENT events)": "SELECT count(*) FROM {ev} AND t.event_type='ACCOUNT_DELINQUENT'",
    "delinquency bucket transitions": "SELECT count(*) FROM {ev} AND t.event_type='DELINQUENCY_BUCKET_CHANGED'",
    "delinquency cured (DELINQUENCY_CURED events)": "SELECT count(*) FROM {ev} AND t.event_type='DELINQUENCY_CURED'",
    "cured while account remains active": "SELECT count(*) FROM {ev} AND t.event_type='DELINQUENCY_CURED' AND a.status='ACTIVE'",
    "payment after simulated collection follow-up": "SELECT count(*) FROM {pt} AND t.payment_context='POST_COLLECTION_FOLLOWUP' AND t.status='POSTED'",
    "failed payment attempt": "SELECT count(*) FROM {pt} AND t.status='FAILED'",
    "pending payment": "SELECT count(*) FROM {pt} AND t.status='PENDING'",
    "posted payment reversal": "SELECT count(*) FROM {pt} AND t.txn_type='REVERSAL'",
    "late-arriving payment (posted after its value date)": "SELECT count(*) FROM {pt} AND t.status='POSTED' AND (t.posted_at AT TIME ZONE 'Asia/Karachi')::date > t.effective_date",
    "payment on a non-business day (weekend)": "SELECT count(*) FROM {pt} AND t.status='POSTED' AND extract(isodow FROM t.effective_date) IN (6,7)",
    "duplicate event delivery (same event_id)": "SELECT count(*) FROM {dl} AND t.is_duplicate",
    "delayed / out-of-order event delivery": "SELECT count(*) FROM {dl} AND t.delivery_status='DELAYED'",
    "restructured loan (schedule v2)": "SELECT count(*) FROM {ev} AND t.event_type='ACCOUNT_RESTRUCTURED'",
    "REPAYMENT_SCHEDULE_CHANGED events": "SELECT count(*) FROM {ev} AND t.event_type='REPAYMENT_SCHEDULE_CHANGED'",
    "early loan settlement": "SELECT count(*) FROM {ac} AND t.close_reason='EARLY_SETTLEMENT'",
    "loan closed at maturity": "SELECT count(*) FROM {ac} AND t.close_reason IN ('MATURED','PAID_OFF_EARLY')",
    "card account closure": "SELECT count(*) FROM {ac} AND t.close_reason='CUSTOMER_REQUEST'",
    "customer with multiple accounts": "SELECT count(*) FROM (SELECT customer_id FROM accounts WHERE run_id=%(r)s GROUP BY 1 HAVING count(*)>1) x",
    "customer with several overdue accounts": "SELECT count(*) FROM (SELECT a.customer_id FROM delinquency_snapshots d JOIN accounts a USING (account_id) WHERE a.run_id=%(r)s AND d.snapshot_reason='AS_OF' AND d.bucket<>'CURRENT' GROUP BY 1 HAVING count(*)>1) x",
    "amount rounding edge (row left with PKR 0 < remaining <= 1)": "SELECT count(*) FROM {rs} AND t.status<>'SUPERSEDED' AND t.total_due-t.principal_paid-t.interest_paid-t.interest_waived BETWEEN 0.01 AND 1.00",
    "installment due on a non-business day (effective due rolled)": "SELECT count(*) FROM {rs} AND t.effective_due_date>t.due_date",
    "asset under recovery review / repossessed": "SELECT count(*) FROM {fa} AND t.collateral_status IN ('UNDER_RECOVERY_REVIEW','REPOSSESSED')",
    "card restricted (blocked/suspended)": "SELECT count(*) FROM {cd} AND t.card_status IN ('TEMPORARY_BLOCK','SUSPENDED')",
}


def scenario_coverage(conn, run_id) -> dict[str, int]:
    fmt = dict(rs=scope("repayment_schedules"), cs=scope("card_statements"), ds=scope("delinquency_snapshots"), ev=scope("banking_events"),
               pt=scope("payment_transactions"), dl=scope("event_delivery_status"), ac=scope("accounts"), fa=scope("financed_assets"),
               cd=scope("credit_card_details"))
    return {name: conn.execute(sql.format(**fmt), {"r": run_id}).fetchone()[0] for name, sql in SCENARIOS.items()}


def build_report(conn: psycopg.Connection, run_id: str, max_dpd_accounts: int | None = None) -> dict:
    run = conn.execute("SELECT seed, profile, as_of_date, config, generation_seconds, ingestion_seconds, status FROM seed_runs WHERE run_id=%s", (run_id,)).fetchone()
    if not run:
        raise SystemExit(f"unknown run '{run_id}'")
    cfg = GenConfig(**(run[3] if isinstance(run[3], dict) else json.loads(run[3])))
    counts = integrity.table_counts(conn, run_id)
    n_accounts = counts["accounts"]
    sample_mod = 1 if n_accounts <= 20_000 else 4
    checks: list[Check] = []
    checks += integrity.run_integrity_checks(conn, run_id)
    checks += financial.run_financial_checks(conn, run_id, sample_mod=sample_mod)
    checks += temporal.run_temporal_checks(conn, run_id, run[2], cfg.policy, max_dpd_accounts)
    stats = statistical.profile(conn, run_id, cfg)
    checks += statistical.soft_checks(stats, cfg)
    coverage = scenario_coverage(conn, run_id)
    critical_fail = [c for c in checks if c.critical and not c.passed]
    return dict(
        run_id=run_id, generated_at=datetime.now(timezone.utc).isoformat(), seed=run[0], profile=run[1], reference_date=str(run[2]),
        business_timezone=cfg.business_timezone, generation_seconds=float(run[4]) if run[4] is not None else None,
        ingestion_seconds=float(run[5]) if run[5] is not None else None, record_counts=counts, statistics=stats,
        scenario_coverage=coverage, uncovered_scenarios=[k for k, v in coverage.items() if v == 0],
        checks=[asdict(c) for c in checks], passed=not critical_fail,
        summary=dict(total=len(checks), passed=sum(c.passed for c in checks), critical_failures=len(critical_fail),
                     soft_warnings=sum((not c.passed) and (not c.critical) for c in checks)))


def to_markdown(r: dict) -> str:
    L = [f"# Data quality report — `{r['run_id']}`", "",
         f"- Result: **{'PASS' if r['passed'] else 'FAIL'}** ({r['summary']['passed']}/{r['summary']['total']} checks passed, "
         f"{r['summary']['critical_failures']} critical failures, {r['summary']['soft_warnings']} soft warnings)",
         f"- Seed: {r['seed']} · profile: {r['profile']} · reference date: {r['reference_date']} · timezone: {r['business_timezone']}",
         f"- Generation: {r['generation_seconds']} s · ingestion: {r['ingestion_seconds']} s", "",
         "> Synthetic data for pipeline development only. Not evidence of real-world model performance.", "", "## Record counts", "",
         "| table | rows |", "|---|---:|"]
    L += [f"| {t} | {n:,} |" for t, n in r["record_counts"].items()]
    L += ["", "## Validation results", "", "| status | category | check | detail |", "|---|---|---|---|"]
    for c in r["checks"]:
        flag = "PASS" if c["passed"] else ("**FAIL**" if c["critical"] else "WARN")
        L.append(f"| {flag} | {c['category']} | {c['name']} | {c['detail']} |")
    s = r["statistics"]
    L += ["", "## Distributions", "", "### Accounts by product", "", *[f"- {k}: {v:,}" for k, v in s["accounts_by_product"].items()],
          "", "### Delinquency at reference date (target vs actual, all accounts; closed accounts count as current)", "", "| bucket | target | actual |", "|---|---:|---:|"]
    L += [f"| {b} | {v['target']:.2%} | {v['actual']:.2%} |" for b, v in s["delinquency_target_vs_actual"].items()]
    L += ["", "### Risk band (behavioural, as-of)", "", *[f"- {k}: {v:,}" for k, v in s["risk_band_asof"].items()],
          "", "### Installment payment behaviour (obligations due on/before reference date)", "", *[f"- {k}: {v:,}" for k, v in s["payment_behaviour"].items()],
          "", "### Payments", "", *[f"- {k}: {v:,}" for k, v in s["payments_by_status"].items()],
          "", "### Events by type", "", *[f"- {k}: {v:,}" for k, v in s["events_by_type"].items()],
          "", "### Missing values (nullable columns)", "", *[f"- {k}: {v['null_pct']}% null of {v['rows']:,}" for k, v in s["missing_values"].items()],
          "", "### Duplicates", "", *[f"- {k}: {v}" for k, v in s["duplicates"].items()],
          "", "### Outliers (IQR; kept, classified)", "", *[f"- {k}: n={v['n']:,}, upper fence {v['upper_fence']:,}, above fence {v['above_fence']:,}, max {v['max']:,} → {v['classification']}" for k, v in s["outliers"].items()],
          "", "## Scenario coverage", "", "| scenario | records |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in r["scenario_coverage"].items()]
    if r["uncovered_scenarios"]:
        L += ["", "**Not covered in this run:** " + ", ".join(r["uncovered_scenarios"])]
    return "\n".join(L) + "\n"


def write_report(r: dict, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or PROJECT_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / f"{r['run_id']}.json", out_dir / f"{r['run_id']}.md"
    jp.write_text(json.dumps(r, indent=2, default=str))
    mp.write_text(to_markdown(r))
    return jp, mp
