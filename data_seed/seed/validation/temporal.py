"""Temporal validation, including an independent point-in-time recomputation of DPD/arrears."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from seed.config import PolicyConfig
from seed.simulation.financial_rules import ZERO, bucket_for
from seed.validation.integrity import Check, check_sql, scope

C = "temporal"


def run_temporal_checks(conn: psycopg.Connection, run_id: str, as_of: date, policy: PolicyConfig, max_accounts: int | None = None) -> list[Check]:
    out: list[Check] = []
    add = lambda name, sql, **kw: out.append(check_sql(conn, run_id, name, C, sql, **kw))
    add("no payment initiated/posted before account opening",
        f"SELECT count(*) FROM {scope('payment_transactions')} AND (t.initiated_at < a.opened_date::timestamp AT TIME ZONE 'Asia/Karachi')")
    add("no payment effective after it was posted",
        f"SELECT count(*) FROM {scope('payment_transactions')} AND t.status='POSTED' AND t.effective_date > (t.posted_at AT TIME ZONE 'Asia/Karachi')::date")
    add("no transaction or snapshot after the reference date",
        f"""SELECT (SELECT count(*) FROM {scope('payment_transactions')} AND t.initiated_at >= ((%(a)s::date+1)::timestamp AT TIME ZONE 'Asia/Karachi'))
                  + (SELECT count(*) FROM {scope('delinquency_snapshots')} AND t.snapshot_date > %(a)s::date)
                  + (SELECT count(*) FROM {scope('account_balance_snapshots')} AND t.snapshot_date > %(a)s::date)""".replace("%(a)s", f"'{as_of}'"))
    add("no installment due on/before disbursement; due dates strictly increase with installment_no",
        f"""SELECT count(*) FROM {scope('repayment_schedules')} AND (t.due_date <= a.opened_date OR EXISTS (
            SELECT 1 FROM repayment_schedules n WHERE n.account_id=t.account_id AND n.schedule_version=t.schedule_version
              AND n.installment_no=t.installment_no+1 AND n.due_date <= t.due_date))""")
    add("card statement dates strictly increase; statements start after account opening",
        f"""SELECT count(*) FROM {scope('card_statements')} AND (t.statement_date <= a.opened_date OR EXISTS (
            SELECT 1 FROM card_statements n WHERE n.account_id=t.account_id AND n.statement_no=t.statement_no+1 AND n.statement_date<=t.statement_date))""")
    add("event ordering: account_sequence follows occurred_at (non-decreasing)",
        f"""SELECT count(*) FROM {scope('banking_events')} AND EXISTS (SELECT 1 FROM banking_events n WHERE n.account_id=t.account_id
            AND n.account_sequence=t.account_sequence+1 AND n.occurred_at < t.occurred_at)""")
    add("events occur on/after account opening and not after the reference date",
        f"""SELECT count(*) FROM {scope('banking_events')} AND (t.occurred_at < a.opened_date::timestamp AT TIME ZONE 'Asia/Karachi'
            OR t.occurred_at >= ((%(a)s::date+1)::timestamp AT TIME ZONE 'Asia/Karachi'))""".replace("%(a)s", f"'{as_of}'"))
    add("no events after account closure (except the closure itself)",
        f"""SELECT count(*) FROM {scope('banking_events')} AND a.status='CLOSED' AND t.event_type NOT IN ('ACCOUNT_CLOSED','RISK_PROFILE_UPDATED')
            AND t.occurred_at >= ((a.closed_date+1)::timestamp AT TIME ZONE 'Asia/Karachi')""")
    add("delinquency snapshots never before opening or after closure",
        f"SELECT count(*) FROM {scope('delinquency_snapshots')} AND (t.snapshot_date < a.opened_date OR (a.closed_date IS NOT NULL AND t.snapshot_date > a.closed_date))")
    add("DPD progression: without payments between snapshots DPD never decreases",
        f"""SELECT count(*) FROM (SELECT t.account_id, t.dpd, lead(t.dpd) OVER w AS nd, t.snapshot_date, lead(t.snapshot_date) OVER w AS nxt
            FROM {scope('delinquency_snapshots')} WINDOW w AS (PARTITION BY t.account_id ORDER BY t.snapshot_date, t.snapshot_reason DESC)) x
            WHERE nd IS NOT NULL AND nd < dpd AND NOT EXISTS (SELECT 1 FROM payment_transactions p WHERE p.account_id=x.account_id AND p.status='POSTED'
              AND (p.posted_at AT TIME ZONE 'Asia/Karachi')::date > x.snapshot_date - 1 AND (p.posted_at AT TIME ZONE 'Asia/Karachi')::date <= x.nxt)
              AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.account_id=x.account_id AND a.is_restructured)""")
    add("AS_OF delinquency snapshot exists for every active account",
        f"SELECT count(*) FROM {scope('accounts')} AND t.status='ACTIVE' AND NOT EXISTS (SELECT 1 FROM delinquency_snapshots d WHERE d.account_id=t.account_id AND d.snapshot_reason='AS_OF')")
    out.append(recompute_dpd(conn, run_id, policy, max_accounts))
    return out


def recompute_dpd(conn: psycopg.Connection, run_id: str, policy: PolicyConfig, max_accounts: int | None) -> Check:
    """For every stored delinquency snapshot re-derive (dpd, overdue_amount) point-in-time from
    obligations + allocations + transaction posting dates, and compare."""
    tol, grace = policy.tolerance, policy.grace_days
    limit = f"LIMIT {int(max_accounts)}" if max_accounts else ""
    acct_rows = conn.execute(
        f"SELECT account_id, closed_date FROM accounts WHERE run_id=%s ORDER BY account_id {limit}", (run_id,)).fetchall()
    ids = [r[0] for r in acct_rows]
    closed = {r[0]: r[1] for r in acct_rows}
    obls: dict = defaultdict(dict)       # account -> oid -> [eff_due, due, superseded_on]
    for acct, oid, eff, due, sup, st in conn.execute(
            """SELECT account_id, schedule_id, effective_due_date, total_due, superseded_on, status FROM repayment_schedules
               WHERE account_id = ANY(%s)""", (ids,)):
        obls[acct][oid] = [eff, due, sup, st]
    for acct, oid, eff, due in conn.execute(
            "SELECT account_id, statement_id, effective_due_date, own_minimum_due FROM card_statements WHERE account_id = ANY(%s) AND own_minimum_due > 0", (ids,)):
        obls[acct][oid] = [eff, due, None, "STMT"]
    moves: dict = defaultdict(list)      # account -> [(posted_date, oid, signed amount)]
    for acct, sid, stid, typ, comp, amt, posted in conn.execute(
            """SELECT al.account_id, al.schedule_id, al.statement_id, al.allocation_type, al.component, al.amount,
                      (p.posted_at AT TIME ZONE 'Asia/Karachi')::date
               FROM payment_allocations al JOIN payment_transactions p USING (transaction_id)
               WHERE al.account_id = ANY(%s) AND (al.schedule_id IS NOT NULL OR al.component='MIN_DUE')""", (ids,)):
        oid = sid or stid
        if oid is not None:
            moves[acct].append((posted, oid, amt if typ == "APPLY" else -amt))
    checked = bad = 0
    first = ""
    for acct, d, reason, dpd, overdue, bucket in conn.execute(
            "SELECT account_id, snapshot_date, snapshot_reason, dpd, overdue_amount, bucket FROM delinquency_snapshots WHERE account_id = ANY(%s)", (ids,)):
        paid: dict = defaultdict(Decimal)
        for pd_, oid, amt in moves[acct]:
            if pd_ <= d:
                paid[oid] += amt
        e_dpd, e_over, oldest = 0, ZERO, None
        for oid, (eff, due, sup, st) in sorted(obls[acct].items(), key=lambda kv: (kv[1][0], str(kv[0]))):
            if sup is not None and sup <= d:
                continue
            if st == "SETTLED_EARLY" and closed.get(acct) and closed[acct] <= d:
                continue
            rem = due - paid[oid]
            if st == "SETTLED_EARLY":
                continue                       # settled-early rows are only ever future rows; not overdue
            if rem > tol and oldest is None and eff < d:
                oldest = eff
            if rem > tol and eff < d:
                e_over += rem
        e_dpd = (d - oldest).days if oldest else 0
        checked += 1
        if e_dpd != dpd or e_over != overdue or bucket != bucket_for(dpd, grace):
            bad += 1
            first = first or f"{acct} {d} {reason}: stored dpd={dpd}/{overdue} recomputed dpd={e_dpd}/{e_over}"
    return Check("delinquency snapshots match independent point-in-time recomputation", C, True, bad == 0,
                 f"{checked} snapshots over {len(ids)} accounts" + (f"; first: {first}" if bad else ""), bad)
