"""FROZEN snapshot of the schema as of migration 0001 (do not edit; later changes are new migrations).

Conventions: snake_case, UUID surrogate keys (deterministic uuid5 from the run id), NUMERIC(16,2)
for money, timestamptz for instants, DATE for business dates, explicit CHECK constraints.
Deleting a run cascades through customers -> accounts -> everything; CMS-owned tables use RESTRICT
so a seed-data cleanup can never silently destroy CMS work.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, MetaData,
    Numeric, String, Table, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"})

MONEY = Numeric(16, 2)
TS = DateTime(timezone=True)
PRODUCT_CATEGORIES = ("PERSONAL_LOAN", "CREDIT_CARD", "ASSET_FINANCING")
BUCKETS = ("CURRENT", "DPD_1_30", "DPD_31_60", "DPD_61_90", "DPD_90_PLUS")
EVENT_TYPES = (
    "ACCOUNT_CREATED", "LOAN_DISBURSED", "CARD_STATEMENT_GENERATED", "INSTALLMENT_DUE", "PAYMENT_ATTEMPT_FAILED",
    "PAYMENT_POSTED", "PAYMENT_REVERSED", "ACCOUNT_DELINQUENT", "DELINQUENCY_BUCKET_CHANGED", "DELINQUENCY_CURED",
    "REPAYMENT_SCHEDULE_CHANGED", "ACCOUNT_RESTRUCTURED", "RISK_PROFILE_UPDATED", "ACCOUNT_CLOSED")


def _in(col: str, values) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


def pk(name: str = "id"):
    return Column(name, UUID(as_uuid=True), primary_key=True)


def fk(name: str, target: str, *, nullable=False, ondelete="CASCADE", **kw):
    return Column(name, UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, **kw)


# ---------------------------------------------------------------- reference / master
seed_runs = Table(
    "seed_runs", metadata,
    Column("run_id", String(80), primary_key=True),
    Column("seed", BigInteger, nullable=False), Column("profile", String(20), nullable=False),
    Column("as_of_date", Date, nullable=False), Column("config", JSONB, nullable=False),
    Column("config_hash", String(64), nullable=False),
    Column("status", String(20), nullable=False, server_default="LOADING"),
    Column("row_counts", JSONB), Column("generation_seconds", Numeric(12, 3)), Column("ingestion_seconds", Numeric(12, 3)),
    Column("created_at", TS, nullable=False, server_default=text("now()")), Column("finished_at", TS),
    CheckConstraint(_in("status", ("LOADING", "LOADED", "FAILED")), name="status"),
)

branches = Table(
    "branches", metadata, pk("branch_id"),
    Column("branch_code", String(20), nullable=False, unique=True), Column("branch_name", String(120), nullable=False),
    Column("city", String(60), nullable=False), Column("province", String(60), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
)

products = Table(
    "products", metadata, pk("product_id"),
    Column("product_code", String(30), nullable=False, unique=True), Column("product_name", String(120), nullable=False),
    Column("category", String(20), nullable=False), Column("currency", String(3), nullable=False, server_default="PKR"),
    Column("config", JSONB, nullable=False), Column("is_synthetic", Boolean, nullable=False, server_default=text("true")),
    CheckConstraint(_in("category", PRODUCT_CATEGORIES), name="category"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
)

collection_teams = Table(
    "collection_teams", metadata, pk("team_id"),
    Column("team_code", String(30), nullable=False, unique=True), Column("team_name", String(120), nullable=False),
    Column("dpd_from", Integer, nullable=False), Column("dpd_to", Integer), Column("description", Text),
    CheckConstraint("dpd_from >= 0 AND (dpd_to IS NULL OR dpd_to >= dpd_from)", name="dpd_range"),
)

collection_agents = Table(
    "collection_agents", metadata, pk("agent_id"),
    Column("agent_code", String(20), nullable=False, unique=True), Column("full_name", String(120), nullable=False),
    fk("team_id", "collection_teams.team_id", ondelete="RESTRICT"),
    fk("branch_id", "branches.branch_id", nullable=True, ondelete="SET NULL"),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
)

collection_policy_rules = Table(
    "collection_policy_rules", metadata, pk("rule_id"),
    Column("rule_code", String(60), nullable=False, unique=True), Column("policy_version", String(30), nullable=False),
    Column("rule_type", String(30), nullable=False),
    fk("product_id", "products.product_id", nullable=True, ondelete="RESTRICT"),
    Column("dpd_min", Integer), Column("dpd_max", Integer), Column("parameters", JSONB, nullable=False),
    Column("description", Text, nullable=False), Column("effective_from", Date, nullable=False),
    CheckConstraint("dpd_max IS NULL OR dpd_min IS NULL OR dpd_max >= dpd_min", name="dpd_range"),
)

customers = Table(
    "customers", metadata, pk("customer_id"),
    Column("run_id", String(80), ForeignKey("seed_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("customer_ref", String(30), nullable=False), Column("full_name", String(120), nullable=False),
    Column("gender", String(10), nullable=False), Column("birth_year", Integer, nullable=False),
    Column("city", String(60), nullable=False), Column("province", String(60), nullable=False),
    Column("employment_type", String(30), nullable=False), Column("income_band", String(20), nullable=False),
    Column("monthly_income", MONEY, nullable=False),
    Column("national_id_token", String(30), nullable=False),   # fictional placeholder, NOT a CNIC
    Column("phone_placeholder", String(30), nullable=False),   # non-routable placeholder
    Column("email_placeholder", String(120), nullable=False),  # RFC 2606 .invalid domain
    fk("home_branch_id", "branches.branch_id", ondelete="RESTRICT"),
    Column("customer_since", Date, nullable=False),
    Column("kyc_status", String(20), nullable=False, server_default="VERIFIED"),
    Column("status", String(20), nullable=False, server_default="ACTIVE"),
    UniqueConstraint("run_id", "customer_ref", name="run_ref"),
    CheckConstraint("monthly_income > 0", name="income_pos"),
    CheckConstraint(_in("income_band", ("LOW", "LOWER_MIDDLE", "MIDDLE", "UPPER_MIDDLE", "HIGH")), name="income_band"),
    CheckConstraint(_in("status", ("ACTIVE", "INACTIVE")), name="status"),
)
Index("ix_customers_run", customers.c.run_id)

accounts = Table(
    "accounts", metadata, pk("account_id"),
    Column("run_id", String(80), ForeignKey("seed_runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("account_number", String(30), nullable=False),
    fk("customer_id", "customers.customer_id"), fk("product_id", "products.product_id", ondelete="RESTRICT"),
    fk("branch_id", "branches.branch_id", ondelete="RESTRICT"),
    Column("currency", String(3), nullable=False, server_default="PKR"),
    Column("status", String(10), nullable=False), Column("opened_date", Date, nullable=False),
    Column("closed_date", Date), Column("close_reason", String(30)),
    Column("is_restructured", Boolean, nullable=False, server_default=text("false")),
    UniqueConstraint("run_id", "account_number", name="run_number"),
    CheckConstraint(_in("status", ("ACTIVE", "CLOSED")), name="status"),
    CheckConstraint("(status = 'CLOSED') = (closed_date IS NOT NULL)", name="closed_consistent"),
    CheckConstraint("closed_date IS NULL OR closed_date >= opened_date", name="closed_after_open"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
)
Index("ix_accounts_customer", accounts.c.customer_id)
Index("ix_accounts_run_product", accounts.c.run_id, accounts.c.product_id)

loan_details = Table(
    "loan_details", metadata, fk("account_id", "accounts.account_id", primary_key=True),
    Column("original_principal", MONEY, nullable=False), Column("term_months", Integer, nullable=False),
    Column("annual_markup_rate", Numeric(7, 4), nullable=False), Column("calculation_method", String(20), nullable=False),
    Column("disbursement_date", Date, nullable=False), Column("first_due_date", Date, nullable=False),
    Column("maturity_date", Date, nullable=False), Column("installment_amount", MONEY, nullable=False),
    Column("total_scheduled_markup", MONEY, nullable=False),
    Column("current_schedule_version", Integer, nullable=False, server_default="1"),
    Column("restructured_on", Date), Column("restructured_principal", MONEY),
    Column("early_settlement_date", Date), Column("early_settlement_amount", MONEY),
    CheckConstraint("original_principal > 0 AND term_months > 0 AND annual_markup_rate >= 0", name="positive"),
    CheckConstraint(_in("calculation_method", ("REDUCING_BALANCE", "FLAT_RATE")), name="method"),
    CheckConstraint("first_due_date > disbursement_date", name="first_due_after_disb"),
)

credit_card_details = Table(
    "credit_card_details", metadata, fk("account_id", "accounts.account_id", primary_key=True),
    Column("credit_limit", MONEY, nullable=False), Column("statement_day", Integer, nullable=False),
    Column("payment_due_days", Integer, nullable=False), Column("min_payment_pct", Numeric(5, 2), nullable=False),
    Column("min_payment_floor", MONEY, nullable=False), Column("monthly_finance_rate", Numeric(6, 3), nullable=False),
    Column("late_fee", MONEY, nullable=False), Column("card_tier", String(20), nullable=False),
    Column("card_status", String(20), nullable=False), Column("restriction_reason", String(60)),
    CheckConstraint("credit_limit > 0 AND statement_day BETWEEN 1 AND 28", name="valid"),
    CheckConstraint(_in("card_status", ("ACTIVE", "TEMPORARY_BLOCK", "SUSPENDED", "CLOSED")), name="status"),
)

financed_assets = Table(
    "financed_assets", metadata, pk("asset_id"),
    fk("account_id", "accounts.account_id", unique=True),
    Column("asset_category", String(30), nullable=False), Column("make", String(60), nullable=False),
    Column("model_name", String(60), nullable=False), Column("model_year", Integer, nullable=False),
    Column("registration_number", String(30), nullable=False), Column("chassis_number", String(30), nullable=False),
    Column("engine_number", String(30), nullable=False),
    Column("purchase_price", MONEY, nullable=False), Column("down_payment", MONEY, nullable=False),
    Column("financed_amount", MONEY, nullable=False),
    Column("collateral_status", String(30), nullable=False),
    Column("lien_marked_on", Date, nullable=False), Column("lien_released_on", Date),
    Column("recovery_review_opened_on", Date), Column("repossessed_on", Date),
    CheckConstraint("purchase_price > 0 AND down_payment >= 0 AND financed_amount > 0", name="positive"),
    CheckConstraint("financed_amount = purchase_price - down_payment", name="financed_equation"),
    CheckConstraint(_in("collateral_status", ("LIEN_ACTIVE", "LIEN_RELEASED", "UNDER_RECOVERY_REVIEW", "REPOSSESSED")),
                    name="collateral_status"),
)

# ---------------------------------------------------------------- financial / servicing
repayment_schedules = Table(
    "repayment_schedules", metadata, pk("schedule_id"), fk("account_id", "accounts.account_id"),
    Column("schedule_version", Integer, nullable=False), Column("installment_no", Integer, nullable=False),
    Column("due_date", Date, nullable=False), Column("effective_due_date", Date, nullable=False),
    Column("opening_principal", MONEY, nullable=False),
    Column("principal_due", MONEY, nullable=False), Column("interest_due", MONEY, nullable=False),
    Column("total_due", MONEY, nullable=False),
    Column("principal_paid", MONEY, nullable=False, server_default="0"), Column("interest_paid", MONEY, nullable=False, server_default="0"),
    Column("interest_waived", MONEY, nullable=False, server_default="0"),
    Column("status", String(20), nullable=False), Column("last_payment_effective_date", Date), Column("superseded_on", Date),
    UniqueConstraint("account_id", "schedule_version", "installment_no", name="acct_ver_no"),
    CheckConstraint("principal_due >= 0 AND interest_due >= 0 AND total_due = principal_due + interest_due", name="amounts"),
    CheckConstraint("principal_paid >= 0 AND interest_paid >= 0 AND interest_waived >= 0", name="paid_nonneg"),
    CheckConstraint("principal_paid <= principal_due AND interest_paid + interest_waived <= interest_due", name="paid_le_due"),
    CheckConstraint("effective_due_date >= due_date", name="eff_due"),
    CheckConstraint(_in("status", ("SCHEDULED", "DUE", "PARTIALLY_PAID", "PAID", "OVERDUE", "SUPERSEDED", "SETTLED_EARLY")), name="status"),
)
Index("ix_repayment_schedules_due", repayment_schedules.c.account_id, repayment_schedules.c.effective_due_date)
Index("ix_repayment_schedules_overdue", repayment_schedules.c.effective_due_date, postgresql_where=text("status = 'OVERDUE'"))

card_statements = Table(
    "card_statements", metadata, pk("statement_id"), fk("account_id", "accounts.account_id"),
    Column("statement_no", Integer, nullable=False), Column("cycle_start_date", Date, nullable=False),
    Column("statement_date", Date, nullable=False), Column("due_date", Date, nullable=False),
    Column("effective_due_date", Date, nullable=False),
    Column("opening_balance", MONEY, nullable=False), Column("purchases_total", MONEY, nullable=False),
    Column("finance_charges", MONEY, nullable=False), Column("fees", MONEY, nullable=False),
    Column("payments_total", MONEY, nullable=False), Column("closing_balance", MONEY, nullable=False),
    Column("own_minimum_due", MONEY, nullable=False), Column("minimum_payment_due", MONEY, nullable=False),
    Column("own_minimum_paid", MONEY, nullable=False, server_default="0"),
    Column("credit_limit", MONEY, nullable=False), Column("status", String(20), nullable=False),
    Column("last_payment_effective_date", Date),
    UniqueConstraint("account_id", "statement_no", name="acct_no"),
    CheckConstraint("closing_balance = opening_balance + purchases_total + finance_charges + fees - payments_total", name="closing_equation"),
    CheckConstraint("closing_balance >= 0 AND opening_balance >= 0 AND purchases_total >= 0 AND finance_charges >= 0 AND fees >= 0 AND payments_total >= 0", name="nonneg"),
    CheckConstraint("own_minimum_due >= 0 AND minimum_payment_due >= own_minimum_due AND minimum_payment_due <= closing_balance", name="minimum"),
    CheckConstraint("own_minimum_paid >= 0 AND own_minimum_paid <= own_minimum_due", name="min_paid"),
    CheckConstraint("effective_due_date >= due_date AND due_date > statement_date", name="dates"),
    CheckConstraint(_in("status", ("OPEN", "PAID", "OVERDUE", "SUPERSEDED")), name="status"),
)
Index("ix_card_statements_due", card_statements.c.account_id, card_statements.c.effective_due_date)

ledger_entries = Table(
    "ledger_entries", metadata, pk("entry_id"), fk("account_id", "accounts.account_id"),
    Column("entry_type", String(25), nullable=False), Column("amount", MONEY, nullable=False),
    Column("entry_date", Date, nullable=False), Column("posted_at", TS, nullable=False),
    CheckConstraint("amount > 0", name="amount_pos"),
    CheckConstraint(_in("entry_type", ("DISBURSEMENT", "CAPITALIZED_INTEREST", "PURCHASE", "FINANCE_CHARGE", "FEE")), name="type"),
)
Index("ix_ledger_entries_account", ledger_entries.c.account_id, ledger_entries.c.posted_at)

payment_transactions = Table(
    "payment_transactions", metadata, pk("transaction_id"), fk("account_id", "accounts.account_id"),
    Column("txn_type", String(10), nullable=False), Column("status", String(10), nullable=False),
    Column("amount", MONEY, nullable=False), Column("currency", String(3), nullable=False, server_default="PKR"),
    Column("channel", String(20), nullable=False), Column("initiated_at", TS, nullable=False),
    Column("posted_at", TS), Column("effective_date", Date),
    Column("reverses_transaction_id", UUID(as_uuid=True), ForeignKey("payment_transactions.transaction_id", ondelete="CASCADE")),
    Column("reversal_reason", String(40)), Column("failure_reason", String(40)),
    Column("payment_context", String(30), nullable=False, server_default="REGULAR"),
    Column("idempotency_key", String(80), nullable=False, unique=True),
    CheckConstraint("amount > 0", name="amount_pos"),
    CheckConstraint(_in("txn_type", ("PAYMENT", "REVERSAL")), name="type"),
    CheckConstraint(_in("status", ("PENDING", "POSTED", "FAILED")), name="status"),
    CheckConstraint("(txn_type = 'REVERSAL') = (reverses_transaction_id IS NOT NULL)", name="reversal_ref"),
    CheckConstraint("status <> 'POSTED' OR (posted_at IS NOT NULL AND effective_date IS NOT NULL)", name="posted_fields"),
    CheckConstraint("posted_at IS NULL OR posted_at >= initiated_at", name="posted_after_initiated"),
    CheckConstraint("status <> 'FAILED' OR failure_reason IS NOT NULL", name="failure_reason"),
)
Index("ix_payment_transactions_account", payment_transactions.c.account_id, payment_transactions.c.posted_at)
Index("ix_payment_transactions_month", payment_transactions.c.posted_at, postgresql_where=text("status = 'POSTED'"))

payment_allocations = Table(
    "payment_allocations", metadata, pk("allocation_id"),
    fk("transaction_id", "payment_transactions.transaction_id"), fk("account_id", "accounts.account_id"),
    Column("allocation_type", String(10), nullable=False), Column("component", String(20), nullable=False),
    Column("amount", MONEY, nullable=False),
    fk("schedule_id", "repayment_schedules.schedule_id", nullable=True),
    fk("statement_id", "card_statements.statement_id", nullable=True),
    CheckConstraint("amount > 0", name="amount_pos"),
    CheckConstraint(_in("allocation_type", ("APPLY", "REVERSAL")), name="type"),
    CheckConstraint(_in("component", ("INTEREST", "PRINCIPAL", "MIN_DUE", "BILLED_BALANCE", "UNBILLED")), name="component"),
    CheckConstraint("NOT (schedule_id IS NOT NULL AND statement_id IS NOT NULL)", name="single_target"),
)
Index("ix_payment_allocations_txn", payment_allocations.c.transaction_id)
Index("ix_payment_allocations_schedule", payment_allocations.c.schedule_id)
Index("ix_payment_allocations_statement", payment_allocations.c.statement_id)

account_balance_snapshots = Table(
    "account_balance_snapshots", metadata, pk("snapshot_id"), fk("account_id", "accounts.account_id"),
    Column("snapshot_date", Date, nullable=False), Column("snapshot_type", String(10), nullable=False),
    Column("outstanding_balance", MONEY, nullable=False), Column("overdue_amount", MONEY, nullable=False),
    Column("billed_balance", MONEY), Column("unbilled_balance", MONEY),
    Column("credit_limit", MONEY), Column("available_credit", MONEY),
    UniqueConstraint("account_id", "snapshot_date", name="acct_date"),
    CheckConstraint(_in("snapshot_type", ("MONTH_END", "AS_OF")), name="type"),
    CheckConstraint("outstanding_balance >= 0 AND overdue_amount >= 0", name="nonneg"),
)

# ---------------------------------------------------------------- risk / delinquency
risk_profiles = Table(
    "risk_profiles", metadata, pk("risk_profile_id"), fk("customer_id", "customers.customer_id"),
    Column("effective_date", Date, nullable=False), Column("profile_source", String(20), nullable=False),
    Column("risk_score", Numeric(5, 2), nullable=False), Column("risk_band", String(12), nullable=False),
    Column("monthly_income", MONEY, nullable=False), Column("monthly_obligation", MONEY, nullable=False),
    Column("burden_ratio", Numeric(7, 4), nullable=False), Column("active_account_count", Integer, nullable=False),
    Column("total_exposure", MONEY, nullable=False), Column("max_dpd_12m", Integer, nullable=False),
    Column("missed_payment_count_12m", Integer, nullable=False), Column("avg_card_utilization", Numeric(7, 4)),
    Column("model_version", String(30), nullable=False),
    UniqueConstraint("customer_id", "effective_date", "profile_source", name="cust_date_src"),
    CheckConstraint("risk_score BETWEEN 0 AND 100", name="score"),
    CheckConstraint(_in("risk_band", ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")), name="band"),
    CheckConstraint(_in("profile_source", ("ORIGINATION", "BEHAVIORAL_AS_OF")), name="source"),
)

delinquency_snapshots = Table(
    "delinquency_snapshots", metadata, pk("snapshot_id"), fk("account_id", "accounts.account_id"),
    Column("snapshot_date", Date, nullable=False), Column("snapshot_reason", String(12), nullable=False),
    Column("dpd", Integer, nullable=False), Column("bucket", String(12), nullable=False),
    Column("overdue_amount", MONEY, nullable=False), Column("overdue_obligation_count", Integer, nullable=False),
    Column("oldest_unpaid_due_date", Date), Column("delinquency_start_date", Date),
    Column("is_collection_eligible", Boolean, nullable=False), Column("policy_version", String(30), nullable=False),
    UniqueConstraint("account_id", "snapshot_date", "snapshot_reason", name="acct_date_reason"),
    CheckConstraint("dpd >= 0 AND overdue_amount >= 0", name="nonneg"),
    CheckConstraint(_in("bucket", BUCKETS), name="bucket"),
    CheckConstraint(_in("snapshot_reason", ("MONTH_END", "TRANSITION", "AS_OF")), name="reason"),
    CheckConstraint("bucket = 'CURRENT' OR dpd > 0", name="bucket_dpd"),
)
Index("ix_delinquency_snapshots_date", delinquency_snapshots.c.snapshot_date, delinquency_snapshots.c.bucket)
Index("ix_delinquency_snapshots_account", delinquency_snapshots.c.account_id, delinquency_snapshots.c.snapshot_date)

# ---------------------------------------------------------------- events
banking_events = Table(
    "banking_events", metadata,
    Column("event_id", String(80), primary_key=True), Column("event_type", String(40), nullable=False),
    Column("source_system", String(30), nullable=False), fk("account_id", "accounts.account_id"),
    Column("account_number", String(30), nullable=False), fk("customer_id", "customers.customer_id"),
    Column("occurred_at", TS, nullable=False), Column("recorded_at", TS, nullable=False),
    Column("schema_version", Integer, nullable=False, server_default="1"),
    Column("account_sequence", Integer, nullable=False), Column("payload", JSONB, nullable=False),
    UniqueConstraint("account_id", "account_sequence", name="acct_seq"),
    CheckConstraint("recorded_at >= occurred_at", name="recorded_after_occurred"),
    CheckConstraint(_in("event_type", EVENT_TYPES), name="type"),
)
Index("ix_banking_events_occurred", banking_events.c.occurred_at)
Index("ix_banking_events_type", banking_events.c.event_type, banking_events.c.occurred_at)

event_delivery_status = Table(
    "event_delivery_status", metadata, pk("delivery_id"),
    Column("event_id", String(80), ForeignKey("banking_events.event_id", ondelete="CASCADE"), nullable=False),
    Column("attempt_no", Integer, nullable=False), Column("delivered_at", TS, nullable=False),
    Column("delivery_status", String(12), nullable=False), Column("is_duplicate", Boolean, nullable=False),
    UniqueConstraint("event_id", "attempt_no", name="event_attempt"),
    CheckConstraint(_in("delivery_status", ("DELIVERED", "DELAYED", "DUPLICATE")), name="status"),
)
Index("ix_event_delivery_status_delivered", event_delivery_status.c.delivered_at)

# ---------------------------------------------------------------- CMS-owned (schema only, NOT seeded)
collection_cases = Table(
    "collection_cases", metadata, pk("case_id"), fk("account_id", "accounts.account_id", ondelete="RESTRICT"),
    Column("status", String(20), nullable=False), Column("bucket_at_open", String(12), nullable=False),
    Column("opening_event_id", String(80), ForeignKey("banking_events.event_id", ondelete="SET NULL")),
    fk("assigned_team_id", "collection_teams.team_id", nullable=True, ondelete="RESTRICT"),
    fk("assigned_agent_id", "collection_agents.agent_id", nullable=True, ondelete="RESTRICT"),
    Column("opened_at", TS, nullable=False, server_default=text("now()")), Column("closed_at", TS),
    Column("resolution", String(30)),
)
Index("ix_collection_cases_account", collection_cases.c.account_id, collection_cases.c.status)

promises_to_pay = Table(
    "promises_to_pay", metadata, pk("ptp_id"), fk("case_id", "collection_cases.case_id", ondelete="RESTRICT"),
    Column("promised_amount", MONEY, nullable=False), Column("promise_date", Date, nullable=False),
    Column("status", String(20), nullable=False), Column("created_at", TS, nullable=False, server_default=text("now()")),
    CheckConstraint("promised_amount > 0", name="amount_pos"),
)

collection_interactions = Table(
    "collection_interactions", metadata, pk("interaction_id"), fk("case_id", "collection_cases.case_id", ondelete="RESTRICT"),
    fk("agent_id", "collection_agents.agent_id", nullable=True, ondelete="RESTRICT"),
    Column("channel", String(20), nullable=False), Column("outcome", String(30)), Column("notes", Text),
    Column("occurred_at", TS, nullable=False, server_default=text("now()")),
)

escalations = Table(
    "escalations", metadata, pk("escalation_id"), fk("case_id", "collection_cases.case_id", ondelete="RESTRICT"),
    fk("from_team_id", "collection_teams.team_id", nullable=True, ondelete="RESTRICT"),
    fk("to_team_id", "collection_teams.team_id", ondelete="RESTRICT"),
    Column("reason", Text), Column("escalated_at", TS, nullable=False, server_default=text("now()")),
)

# Load order (parents before children) used by the loader; CMS-owned tables are intentionally absent.
LOAD_ORDER = (
    "branches", "products", "collection_teams", "collection_agents", "collection_policy_rules",
    "customers", "accounts", "loan_details", "credit_card_details", "financed_assets",
    "repayment_schedules", "card_statements", "ledger_entries", "payment_transactions", "payment_allocations",
    "account_balance_snapshots", "risk_profiles", "delinquency_snapshots", "banking_events", "event_delivery_status",
)
JSON_COLUMNS = {"config", "parameters", "payload", "row_counts"}
