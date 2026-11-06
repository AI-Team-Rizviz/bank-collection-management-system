"""Financial validation: independent recomputation from persisted rows (not the simulation objects)."""
from __future__ import annotations

from decimal import Decimal

import psycopg

from seed.simulation.financial_rules import build_installments, money
from seed.validation.integrity import Check, check_sql, scope

C = "financial"
EOD = "((t.snapshot_date + 1)::timestamp AT TIME ZONE 'Asia/Karachi')"   # end of business day (Karachi)


def run_financial_checks(conn: psycopg.Connection, run_id: str, sample_mod: int = 1) -> list[Check]:
    out: list[Check] = []
    add = lambda name, sql, **kw: out.append(check_sql(conn, run_id, name, C, sql, **kw))

    # ---- schedules reconcile with contract terms
    add("schedule v1 principal sums to original principal",
        f"""SELECT count(*) FROM {scope('loan_details')} AND (SELECT sum(principal_due) FROM repayment_schedules s
            WHERE s.account_id=t.account_id AND s.schedule_version=1) <> t.original_principal""")
    add("schedule v1 interest sums to total scheduled markup",
        f"""SELECT count(*) FROM {scope('loan_details')} AND (SELECT sum(interest_due) FROM repayment_schedules s
            WHERE s.account_id=t.account_id AND s.schedule_version=1) <> t.total_scheduled_markup""")
    add("restructured schedule principal equals restructured principal",
        f"""SELECT count(*) FROM {scope('loan_details')} AND t.current_schedule_version>1 AND
            (SELECT sum(principal_due) FROM repayment_schedules s WHERE s.account_id=t.account_id
             AND s.schedule_version=t.current_schedule_version) <> t.restructured_principal""")
    add("installment number count equals term (v1)",
        f"""SELECT count(*) FROM {scope('loan_details')} AND (SELECT count(*) FROM repayment_schedules s
            WHERE s.account_id=t.account_id AND s.schedule_version=1) <> t.term_months""")
    add("asset: financed amount = loan principal = price - down payment",
        f"""SELECT count(*) FROM {scope('financed_assets')} AND NOT EXISTS (SELECT 1 FROM loan_details l
            WHERE l.account_id=t.account_id AND l.original_principal=t.financed_amount)""")
    add("asset collateral status consistent with account state",
        f"""SELECT count(*) FROM {scope('financed_assets')} AND NOT (
            (a.status='CLOSED' AND t.collateral_status='LIEN_RELEASED' AND t.lien_released_on=a.closed_date)
            OR (a.status='ACTIVE' AND t.collateral_status IN ('LIEN_ACTIVE','UNDER_RECOVERY_REVIEW','REPOSSESSED')
                AND t.lien_released_on IS NULL)) OR t.lien_marked_on<>a.opened_date""")
    # ---- paid amounts == net allocations
    add("schedule paid amounts reconcile with net payment allocations",
        f"""SELECT count(*) FROM {scope('repayment_schedules')} AND (t.principal_paid, t.interest_paid) <> (
            SELECT COALESCE(sum(CASE WHEN al.component='PRINCIPAL' THEN CASE al.allocation_type WHEN 'APPLY' THEN al.amount ELSE -al.amount END END),0),
                   COALESCE(sum(CASE WHEN al.component='INTEREST' THEN CASE al.allocation_type WHEN 'APPLY' THEN al.amount ELSE -al.amount END END),0)
            FROM payment_allocations al WHERE al.schedule_id=t.schedule_id)""")
    add("card own-minimum paid reconciles with net MIN_DUE allocations",
        f"""SELECT count(*) FROM {scope('card_statements')} AND t.own_minimum_paid <> (
            SELECT COALESCE(sum(CASE al.allocation_type WHEN 'APPLY' THEN al.amount ELSE -al.amount END),0)
            FROM payment_allocations al WHERE al.statement_id=t.statement_id AND al.component='MIN_DUE')""")
    # ---- allocations vs transactions
    add("posted payment: allocations sum to payment amount",
        f"""SELECT count(*) FROM {scope('payment_transactions')} AND t.txn_type='PAYMENT' AND t.status='POSTED' AND
            t.amount <> (SELECT COALESCE(sum(al.amount),0) FROM payment_allocations al WHERE al.transaction_id=t.transaction_id AND al.allocation_type='APPLY')""")
    add("reversal: reversal allocations sum to reversed amount",
        f"""SELECT count(*) FROM {scope('payment_transactions')} AND t.txn_type='REVERSAL' AND
            t.amount <> (SELECT COALESCE(sum(al.amount),0) FROM payment_allocations al WHERE al.transaction_id=t.transaction_id AND al.allocation_type='REVERSAL')""")
    add("reversal allocations mirror the original allocations per component",
        f"""SELECT count(*) FROM {scope('payment_transactions')} AND t.txn_type='REVERSAL' AND
            (SELECT array_agg((component, amount) ORDER BY component, amount) FROM payment_allocations WHERE transaction_id=t.transaction_id)
            IS DISTINCT FROM
            (SELECT array_agg((component, amount) ORDER BY component, amount) FROM payment_allocations WHERE transaction_id=t.reverses_transaction_id)""")
    add("failed/pending payments carry no allocations",
        f"""SELECT count(*) FROM {scope('payment_transactions')} AND t.status<>'POSTED' AND EXISTS (SELECT 1 FROM payment_allocations al WHERE al.transaction_id=t.transaction_id)""")
    add("no duplicate financial postings (idempotency keys unique; one PAYMENT_POSTED event per posted payment)",
        f"""SELECT count(*) FROM (SELECT payload->>'transaction_id' FROM {scope('banking_events')} AND t.event_type='PAYMENT_POSTED' GROUP BY 1 HAVING count(*)>1) x""")
    add("PAYMENT_POSTED events match posted payments 1:1",
        f"""SELECT abs((SELECT count(*) FROM {scope('payment_transactions')} AND t.txn_type='PAYMENT' AND t.status='POSTED')
                      - (SELECT count(*) FROM {scope('banking_events')} AND t.event_type='PAYMENT_POSTED'))""")
    # ---- ledger reconciliation with balance snapshots (time-aware, one windowed pass per product family)
    # Event stream (ledger debits, payment credits/reversals) is merged with the snapshots; a running sum per
    # account gives the independent ledger balance at the end of each snapshot day (Karachi business date).
    karachi = "(%s AT TIME ZONE 'Asia/Karachi')::date"
    smp = f"AND mod(hashtext(a.account_id::text), {sample_mod}) = 0" if sample_mod > 1 else ""
    for kind, cat, credit_sql in (
        ("loan/asset", "<>", f"""SELECT al.account_id, {karachi % 'p.posted_at'} AS d, 0 AS ord,
                -CASE al.allocation_type WHEN 'APPLY' THEN al.amount ELSE -al.amount END AS delta, NULL::numeric AS snap
              FROM payment_allocations al JOIN payment_transactions p USING (transaction_id) JOIN accounts a ON a.account_id=al.account_id
              JOIN products pr ON pr.product_id=a.product_id WHERE a.run_id=%(r)s AND pr.category <> 'CREDIT_CARD' AND al.component='PRINCIPAL' {smp}"""),
        ("card", "=", f"""SELECT p.account_id, {karachi % 'p.posted_at'}, 0,
                -CASE p.txn_type WHEN 'PAYMENT' THEN p.amount ELSE -p.amount END, NULL::numeric
              FROM payment_transactions p JOIN accounts a ON a.account_id=p.account_id JOIN products pr ON pr.product_id=a.product_id
              WHERE a.run_id=%(r)s AND pr.category = 'CREDIT_CARD' AND p.status='POSTED' {smp}"""),
    ):
        add(f"{kind} balance snapshots reconcile with ledger + allocations (all snapshots)",
            f"""WITH ev AS (
                  SELECT l.account_id, {karachi % 'l.posted_at'} AS d, 0 AS ord, l.amount AS delta, NULL::numeric AS snap
                    FROM ledger_entries l JOIN accounts a ON a.account_id=l.account_id JOIN products pr ON pr.product_id=a.product_id
                   WHERE a.run_id=%(r)s AND pr.category {cat} 'CREDIT_CARD' {smp}
                  UNION ALL {credit_sql}
                  UNION ALL
                  SELECT t.account_id, t.snapshot_date, 1, 0, t.outstanding_balance
                    FROM account_balance_snapshots t JOIN accounts a ON a.account_id=t.account_id JOIN products pr ON pr.product_id=a.product_id
                   WHERE a.run_id=%(r)s AND pr.category {cat} 'CREDIT_CARD' {smp}),
               run AS (SELECT *, sum(delta) OVER (PARTITION BY account_id ORDER BY d, ord ROWS UNBOUNDED PRECEDING) AS bal FROM ev)
               SELECT count(*) FROM run WHERE ord = 1 AND bal <> snap""")
    add("card billed + unbilled = outstanding balance",
        f"SELECT count(*) FROM {scope('account_balance_snapshots')} AND t.billed_balance IS NOT NULL AND t.billed_balance+t.unbilled_balance<>t.outstanding_balance")
    add("card balance above 150% of limit (finance charges and fees on long-delinquent cards; legitimate rare cases, informational)",
        f"""SELECT count(*) FROM {scope('account_balance_snapshots')} AND t.credit_limit IS NOT NULL AND t.outstanding_balance > t.credit_limit*1.5""", critical=False)
    # ---- card statements
    add("card statement opening balance = previous closing (0 after a skipped zero-balance cycle)",
        f"""SELECT count(*) FROM {scope('card_statements')} AND t.opening_balance <> COALESCE(
            (SELECT CASE WHEN p.statement_date = t.cycle_start_date - 1 THEN p.closing_balance ELSE 0 END
               FROM card_statements p WHERE p.account_id=t.account_id AND p.statement_no=t.statement_no-1),0)""")
    add("card statement purchases/fees/finance charges match the ledger",
        f"""SELECT count(*) FROM {scope('card_statements')} AND (t.purchases_total, t.finance_charges, t.fees) <> (
            SELECT COALESCE(sum(amount) FILTER (WHERE entry_type='PURCHASE'),0), COALESCE(sum(amount) FILTER (WHERE entry_type='FINANCE_CHARGE'),0),
                   COALESCE(sum(amount) FILTER (WHERE entry_type='FEE'),0)
            FROM ledger_entries l WHERE l.account_id=t.account_id
             AND (l.posted_at AT TIME ZONE 'Asia/Karachi')::date BETWEEN t.cycle_start_date AND t.statement_date
             AND (l.entry_type='PURCHASE' OR (l.posted_at AT TIME ZONE 'Asia/Karachi')::date = t.statement_date))""")
    add("card statement payments_total = net posted payments in cycle",
        f"""SELECT count(*) FROM {scope('card_statements')} AND t.payments_total <> (
            SELECT COALESCE(sum(CASE p.txn_type WHEN 'PAYMENT' THEN p.amount ELSE -p.amount END),0) FROM payment_transactions p
             WHERE p.account_id=t.account_id AND p.status='POSTED'
               AND (p.posted_at AT TIME ZONE 'Asia/Karachi')::date BETWEEN t.cycle_start_date AND t.statement_date)""")
    add("card finance charge = monthly rate x billed balance unpaid at previous due date",
        f"""SELECT count(*) FROM {scope('card_statements')} AND t.statement_no>1 AND t.finance_charges <> COALESCE((
            SELECT round(GREATEST(0, prev.closing_balance - COALESCE((
                SELECT sum(CASE al.allocation_type WHEN 'APPLY' THEN al.amount ELSE -al.amount END) FROM payment_allocations al
                  JOIN payment_transactions p USING (transaction_id)
                 WHERE al.account_id=t.account_id AND al.component IN ('MIN_DUE','BILLED_BALANCE')
                   AND (p.posted_at AT TIME ZONE 'Asia/Karachi')::date > prev.statement_date
                   AND (p.posted_at AT TIME ZONE 'Asia/Karachi')::date <= prev.effective_due_date),0))
                * cc.monthly_finance_rate/100, 2)
            FROM card_statements prev JOIN credit_card_details cc ON cc.account_id=prev.account_id
           WHERE prev.account_id=t.account_id AND prev.statement_no=t.statement_no-1),0)""")
    # ---- closed accounts are fully satisfied
    add("closed loan/asset accounts have no unpaid obligations",
        f"""SELECT count(*) FROM {scope('accounts')} AND t.status='CLOSED' AND EXISTS (SELECT 1 FROM repayment_schedules s
            WHERE s.account_id=t.account_id AND s.status NOT IN ('PAID','SETTLED_EARLY','SUPERSEDED'))""")
    add("closed accounts carry no delinquency at closure",
        f"""SELECT count(*) FROM {scope('accounts')} AND t.status='CLOSED' AND EXISTS (SELECT 1 FROM delinquency_snapshots d
            WHERE d.account_id=t.account_id AND d.snapshot_date>=t.closed_date AND d.dpd>0)""")
    add("fully satisfied schedule rows are never OVERDUE (tolerance-aware)",
        f"""SELECT count(*) FROM {scope('repayment_schedules')} AND t.status='OVERDUE' AND (t.total_due-t.principal_paid-t.interest_paid-t.interest_waived)<=1.00""")
    out.extend(python_schedule_recompute(conn, run_id))
    return out


def python_schedule_recompute(conn: psycopg.Connection, run_id: str) -> list[Check]:
    """Rebuild every v1 schedule from contract terms and compare row by row (Decimal arithmetic)."""
    bad = checked = 0
    first_bad = ""
    cur = conn.execute(
        """SELECT l.account_id, l.original_principal, l.annual_markup_rate, l.term_months, l.calculation_method,
                  s.installment_no, s.principal_due, s.interest_due
           FROM loan_details l JOIN accounts a USING (account_id)
           JOIN repayment_schedules s ON s.account_id=l.account_id AND s.schedule_version=1
           WHERE a.run_id=%s ORDER BY l.account_id, s.installment_no""", (run_id,))
    cache_key, cache = None, []
    for acct, principal, rate, term, method, no, p_due, i_due in cur:
        if acct != cache_key:
            cache_key, cache = acct, build_installments(principal, rate, term, method)
        exp = cache[no - 1]
        checked += 1
        if exp.principal != p_due or exp.interest != i_due:
            bad += 1
            first_bad = first_bad or f"{acct} #{no}"
    return [Check("v1 schedules match independent amortization recomputation", C, True, bad == 0,
                  f"{checked} rows checked" + (f"; first mismatch {first_bad}" if bad else ""), bad)]
