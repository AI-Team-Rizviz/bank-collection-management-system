"""Structural validation: counts, PK/FK/domain integrity, completeness. All checks are SQL, scoped to a run."""
from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from seed.models.tables import LOAD_ORDER, metadata


@dataclass
class Check:
    name: str
    category: str
    critical: bool
    passed: bool
    detail: str = ""
    failures: int = 0


_SCOPE = {  # table -> FROM/WHERE producing only that run's rows
    "customers": "customers t WHERE t.run_id = %(r)s",
    "accounts": "accounts t WHERE t.run_id = %(r)s",
    "risk_profiles": "risk_profiles t JOIN customers c USING (customer_id) WHERE c.run_id = %(r)s",
    "banking_events": "banking_events t JOIN accounts a USING (account_id) WHERE a.run_id = %(r)s",
    "event_delivery_status": "event_delivery_status t JOIN banking_events e USING (event_id) JOIN accounts a USING (account_id) WHERE a.run_id = %(r)s",
}
GLOBAL_TABLES = {"branches", "products", "collection_teams", "collection_agents", "collection_policy_rules"}
_GLOBAL = GLOBAL_TABLES


def scope(table: str) -> str:
    if table in _SCOPE:
        return _SCOPE[table]
    if table in _GLOBAL:
        return f"{table} t WHERE %(r)s::text IS NOT NULL"
    return f"{table} t JOIN accounts a USING (account_id) WHERE a.run_id = %(r)s"


def table_counts(conn: psycopg.Connection, run_id: str) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {scope(t)}", {"r": run_id}).fetchone()[0] for t in LOAD_ORDER}


def scalar(conn, sql: str, run_id: str):
    return conn.execute(sql, {"r": run_id}).fetchone()[0]


def check_sql(conn, run_id, name, category, sql, critical=True, ok_when_zero=True, detail="") -> Check:
    try:
        n = scalar(conn, sql, run_id)
    except psycopg.Error as exc:     # a check that cannot run must fail loudly, never pass silently
        conn.rollback()
        return Check(name, category, critical, False, f"check could not run: {type(exc).__name__}: {str(exc).splitlines()[0][:150]}", -1)
    return Check(name, category, critical, n == 0 if ok_when_zero else n > 0, detail or (f"{n} violating rows" if n else "ok"), int(n))


def run_integrity_checks(conn: psycopg.Connection, run_id: str) -> list[Check]:
    out: list[Check] = []
    c = "structural"
    # Declared PK/FK/UNIQUE/CHECK constraints are enforced by PostgreSQL at load time; re-verify no constraint is NOT VALID.
    out.append(check_sql(conn, run_id, "all constraints validated", c,
                         "SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated"))
    out.append(Check("primary keys unique (enforced by constraints)", c, True, True, f"{len(metadata.tables)} tables"))
    fk_checks = {
        "accounts -> customers": "SELECT count(*) FROM accounts a LEFT JOIN customers c USING (customer_id) WHERE a.run_id=%(r)s AND c.customer_id IS NULL",
        "accounts -> products": "SELECT count(*) FROM accounts a LEFT JOIN products p USING (product_id) WHERE a.run_id=%(r)s AND p.product_id IS NULL",
        "schedules -> accounts": "SELECT count(*) FROM repayment_schedules s LEFT JOIN accounts a USING (account_id) WHERE a.account_id IS NULL",
        "payments -> accounts": "SELECT count(*) FROM payment_transactions s LEFT JOIN accounts a USING (account_id) WHERE a.account_id IS NULL",
        "allocations -> posted transactions": f"SELECT count(*) FROM {scope('payment_allocations')} AND NOT EXISTS (SELECT 1 FROM payment_transactions p WHERE p.transaction_id=t.transaction_id AND p.status='POSTED')",
        "events -> accounts": "SELECT count(*) FROM banking_events e LEFT JOIN accounts a USING (account_id) WHERE a.account_id IS NULL",
    }
    for n, sql in fk_checks.items():
        out.append(check_sql(conn, run_id, f"FK integrity: {n}", c, sql))
    # product/category consistency
    out.append(check_sql(conn, run_id, "loan_details only on installment products", c,
        f"SELECT count(*) FROM {scope('loan_details')} AND NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id=a.product_id AND p.category IN ('PERSONAL_LOAN','ASSET_FINANCING'))"))
    out.append(check_sql(conn, run_id, "credit_card_details only on CREDIT_CARD", c,
        f"SELECT count(*) FROM {scope('credit_card_details')} AND NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id=a.product_id AND p.category='CREDIT_CARD')"))
    out.append(check_sql(conn, run_id, "every account has exactly one product-detail row", c,
        """SELECT count(*) FROM accounts a JOIN products p USING (product_id) WHERE a.run_id=%(r)s AND
           ((p.category='CREDIT_CARD') <> EXISTS (SELECT 1 FROM credit_card_details d WHERE d.account_id=a.account_id)
            OR (p.category<>'CREDIT_CARD') <> EXISTS (SELECT 1 FROM loan_details d WHERE d.account_id=a.account_id))"""))
    out.append(check_sql(conn, run_id, "one financed asset per ASSET_FINANCING account (none elsewhere)", c,
        """SELECT count(*) FROM accounts a JOIN products p USING (product_id) WHERE a.run_id=%(r)s AND
           (p.category='ASSET_FINANCING') <> EXISTS (SELECT 1 FROM financed_assets f WHERE f.account_id=a.account_id)"""))
    out.append(check_sql(conn, run_id, "every customer has >=1 account and a risk profile", c,
        """SELECT count(*) FROM customers c WHERE c.run_id=%(r)s AND (NOT EXISTS (SELECT 1 FROM accounts a WHERE a.customer_id=c.customer_id)
           OR NOT EXISTS (SELECT 1 FROM risk_profiles r WHERE r.customer_id=c.customer_id))"""))
    out.append(check_sql(conn, run_id, "reversal references a POSTED original payment on the same account", c,
        f"""SELECT count(*) FROM {scope('payment_transactions')} AND t.txn_type='REVERSAL' AND NOT EXISTS (
            SELECT 1 FROM payment_transactions o WHERE o.transaction_id=t.reverses_transaction_id AND o.account_id=t.account_id
              AND o.txn_type='PAYMENT' AND o.status='POSTED' AND o.amount=t.amount AND o.posted_at<=t.posted_at)"""))
    out.append(check_sql(conn, run_id, "no payment reversed more than once", c,
        f"SELECT count(*) FROM (SELECT reverses_transaction_id FROM {scope('payment_transactions')} AND t.txn_type='REVERSAL' GROUP BY 1 HAVING count(*)>1) x"))
    # completeness
    for table, cols in {"customers": ["full_name", "monthly_income", "home_branch_id"], "accounts": ["opened_date", "product_id", "branch_id"],
                        "payment_transactions": ["amount", "channel", "initiated_at"]}.items():
        cond = " OR ".join(f"t.{x} IS NULL" for x in cols)
        out.append(check_sql(conn, run_id, f"required fields complete: {table}", c, f"SELECT count(*) FROM {scope(table)} AND ({cond})"))
    out.append(check_sql(conn, run_id, "currency is PKR everywhere", c,
        f"SELECT count(*) FROM {scope('accounts')} AND t.currency<>'PKR'", critical=False))
    out.append(check_sql(conn, run_id, "no real-looking contact data (placeholders only)", c,
        f"""SELECT count(*) FROM {scope('customers')} AND (t.email_placeholder NOT LIKE '%%@example.invalid'
            OR t.phone_placeholder NOT LIKE '+92-000-%%' OR t.national_id_token NOT LIKE 'SYN-ID-%%')"""))
    return out
