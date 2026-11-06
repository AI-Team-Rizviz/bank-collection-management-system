# Bank Collection Management System — Synthetic Data Seeder

A deterministic, financially consistent **synthetic banking data generator and PostgreSQL seeder** for developing a
Pakistani retail-bank Collection Management System (CMS). It simulates personal loans, credit cards and scooty/bike
asset financing chronologically (schedules, statements, payments, reversals, delinquency, restructuring, events), loads
them into PostgreSQL, validates them, and produces a data-quality report.

> **Everything is synthetic.** Product terms, markup rates, minimum-payment rules, delinquency policy and the
> 75/12/6/4/3 delinquency mix are *test assumptions*. They are **not** Allied Bank Pakistan's (or any bank's) real
> products or policies. All people, CNIC-like tokens, phone numbers and e-mails are fictional placeholders
> (`SYN-ID-…`, `+92-000-…`, `…@example.invalid`). The data is for pipeline development, **not** evidence of real-world
> model performance or suitability for credit decisions.

## 1. Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate          # Python >= 3.11
pip install -e ".[dev]"                                     # sqlalchemy 2, psycopg 3, alembic, pydantic, typer, pytest
cp .env.example .env                                        # then edit DATABASE_URL (never commit .env)

python -m seed.cli check-db                                 # connectivity (password is never printed)
python -m seed.cli migrate                                  # Alembic migrations
python -m seed.cli run --profile small --seed 42            # migrate + generate + load + validate + report
pytest                                                      # unit + golden + DB integration tests
```

## 2. Database configuration

`DATABASE_URL` is read from the process environment, then `.env` (no `$`-interpolation, so a literal `$` in a password is fine):

```
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/bank-cms
```

* Special characters in the password should be URL-encoded (`@`→`%40`, `/`→`%2F`, `:`→`%3A`); `$` is accepted as-is.
* Exactly **one** `DATABASE_URL=` prefix. A duplicated prefix (`DATABASE_URL=DATABASE_URL=postgresql://…`) is tolerated
  with a warning and should be fixed in `.env`.
* The URL is only ever printed with the password masked. `.env` is git-ignored.

## 3. CLI

| command | purpose |
|---|---|
| `python -m seed.cli check-db` | verify `DATABASE_URL` and connectivity |
| `python -m seed.cli migrate` | apply Alembic migrations (`0001` schema, `0002` per-account idempotency keys, `0003` index) |
| `python -m seed.cli generate --profile small --seed 42 --as-of-date 2026-11-06` | generate JSONL files under `data/<run_id>/` (no DB needed) so they can be inspected first |
| `python -m seed.cli ingest [--run-id R]` | load a generated directory into PostgreSQL (idempotent) |
| `python -m seed.cli run --profile large --seed 42` | direct mode: migrate → generate+load chunk by chunk (bounded memory) → validate → report |
| `python -m seed.cli validate [--run-id R]` | all data-quality checks; exit code 1 on critical failures |
| `python -m seed.cli report [--run-id R]` | write `reports/<run_id>.md` and `.json` |
| `python -m seed.cli replay --account LOAN-000001 --order delivery --dedupe` | replay stored events as JSON envelopes |
| `python -m seed.cli list-runs` | list loaded runs |
| `python -m seed.cli reset-run --run-id R --yes-delete-run --confirm R` | delete **one** run (see Safety) |

Profiles: `small` (100 customers), `medium` (1,000), `large` (10,000), `custom` (`--customers N`). Accounts ≈ 1.5 × customers
(40% personal loans / 40% cards / 20% asset financing). Overrides can come from a TOML file (`--config`, see
`seed/config.example.toml`); precedence is defaults < TOML < CLI flags. Run id = `<profile>-n<customers>-seed<seed>-<as_of>`.

**Safety.** Nothing is dropped or truncated implicitly. `reset-run` deletes only the named run (cascading through its
customers/accounts/ledger/events), never reference data or other runs, requires `--yes-delete-run` *and* the run id typed
again, and is blocked by foreign keys if CMS-owned records (cases, promises…) reference the run's accounts.
Re-running `run`/`ingest` for the same seed and configuration inserts **zero** new rows; the same run id with a different
configuration or generator version is refused. After every load the number of database rows is compared with the number
generated, so `ON CONFLICT DO NOTHING` can never silently hide a dropped row.

## 4. Schema overview

Defined once in `seed/models/tables.py` (SQLAlchemy Core); migrations in `migrations/`. Surrogate keys are deterministic
UUIDv5 values derived from the run id; business keys (`account_number`, `customer_ref`) are unique per run.

```
customers 1──* accounts *──1 products          branches 1──* accounts / customers
accounts 1──1 loan_details (loans & asset financing)   accounts 1──1 credit_card_details (cards)
accounts 1──1 financed_assets (asset financing only)
accounts 1──* repayment_schedules (versioned; v2 after restructuring)      accounts 1──* card_statements
accounts 1──* ledger_entries (debits: disbursement, purchase, finance charge, fee, capitalised interest)
accounts 1──* payment_transactions (PAYMENT | REVERSAL→original; PENDING | POSTED | FAILED)
payment_transactions 1──* payment_allocations ──> repayment_schedules | card_statements   (APPLY | REVERSAL rows)
accounts 1──* account_balance_snapshots, delinquency_snapshots        customers 1──* risk_profiles
accounts 1──* banking_events 1──* event_delivery_status (duplicates / delays reuse the same event_id)
collection_teams 1──* collection_agents, collection_policy_rules       seed_runs 1──* customers/accounts
CMS-owned, schema only (NOT seeded): collection_cases, promises_to_pay, collection_interactions, escalations
```

Notable constraints: money is `NUMERIC(16,2)` and never negative where meaningless; reversal ⇔ `reverses_transaction_id`;
`financed_amount = purchase_price − down_payment`; `closing_balance = opening + purchases + finance charges + fees − payments`;
paid ≤ due on every obligation; timestamps are `timestamptz`; currency is an explicit ISO code (`PKR`). Deleting a run
cascades; CMS tables use `RESTRICT`. A leakage-safe label view `vw_roll_rate_labels` is included for later ML work.

## 5. How the data is generated

1. **Customers** get a latent risk score (employment/income-driven, independent of gender, age and city), an income band
   and a payment *discipline* = `sigmoid(1.9 − 0.85·risk − 1.8·repayment-burden + noise)`.
2. **Accounts** are sized from income (EMI as a share of income, credit limit as a multiple of income), so higher burden
   → lower discipline → more delinquency. Customers hold 1–4 accounts.
3. **Delinquency targets**: the configured mix is assigned per *account*, worst bucket first, ranking accounts by
   noisy risk + burden (correlated, not deterministic), restricted to accounts whose due dates can actually produce that DPD
   at `as_of`. The target selects the *onset instalment/statement* from which payments stop.
4. **Chronological simulation** (`seed/simulation/engine.py`): each account is replayed from a time-ordered action queue
   (payments, reversals, statements, purchases, restructuring, early settlement). Ledger, allocations, arrears, DPD,
   bucket transitions, snapshots and events are *derived* from that replay — DPD is never assigned.
5. **Scenarios** (all produced through real dated rows): on-time/early/late payments, missed and consecutive missed
   instalments, partial payments, cures (window, on next due date, part-then-full), payments after "collection follow-up",
   failed attempts, pending payments, reversals, late-posted (back-valued) payments, weekend/holiday handling, restructuring,
   early settlement, maturity closure, card closure, card blocks/suspension, collateral recovery review/repossession,
   multi-account customers, rounding edge cases.
6. **Events** are produced from the same replay; delivery simulation adds duplicates (same `event_id`), delayed/out-of-order
   deliveries and late recording.

Determinism: every entity draws from its own RNG seeded by `(seed, entity key)`, so output is identical for the same seed
regardless of chunk size or processing order (tested). `seed.GENERATOR_VERSION` is part of the run's config hash.

## 6. Financial assumptions (all synthetic, all `Decimal`, rounding `ROUND_HALF_UP` to 0.01)

* **Personal loan – reducing balance**: `EMI = P·i / (1 − (1+i)^−n)`, `i = rate/1200`; interest = `round(opening·i)`; principal =
  EMI − interest; the **last** instalment clears the remaining principal (absorbs rounding drift).
* **Asset financing – flat rate**: markup = `P · rate · n/12`, spread evenly; principal spread evenly; last instalment absorbs residue.
* **Instalment allocation**: oldest obligation first; interest then principal.
* **Due dates** keep the contract day-of-month (≤28); `effective_due_date` = next business day (Mon–Fri minus configured holidays).
* **DPD** is end-of-day: `DPD(d) = d − effective_due_date` of the oldest obligation with unpaid amount > tolerance (PKR 1.00) and
  `effective_due_date < d`. Delinquent when `DPD > grace_days` (0). Buckets: 1–30, 31–60, 61–90, 91+ (`DPD_90_PLUS`).
  Only payments **posted** by that day count (so a late-posted, back-valued payment can cause a short delinquency that is cured on posting,
  while `last_payment_effective_date` still shows it was paid on the due date).
* **Cards** are not instalment loans: a statement (distinct from the revolving balance) has an *own minimum*
  `min(closing, max(PKR 500, 5%·closing))` plus unmet earlier minimums. Payments allocate to unmet minimums (oldest first), then billed balance, then
  unbilled purchases. Finance charge = 3.5%/month × billed balance still unpaid at the due date (zero if cleared ⇒ interest-free grace);
  late fee PKR 1,500 if the own minimum was unmet at the due date. Cards are blocked above 30 DPD, suspended above 60 DPD (no new purchases).
* **Reversals** restore exactly the components the original payment was allocated to; later payments are not re-allocated.
* **Restructuring**: unpaid schedule rows are superseded, overdue interest is capitalised (`CAPITALIZED_INTEREST` ledger entry), a new
  schedule version is built (lower rate, new term). **Early settlement** payoff = outstanding principal + interest of the next unpaid instalment; later interest is waived.
* **Balances reconcile with the ledger** (`ledger_entries` debits minus net payment allocations/payments) at every snapshot date.

## 7. Seeding & results

```bash
python -m seed.cli run --profile small  --seed 42        # ~24k rows, <2 s
python -m seed.cli run --profile large  --seed 42        # 10,000 customers / 15,000 accounts (~40 s generate, ~90 s load)
```

Measured on the development machine (large profile, seed 42, `as_of` 2026-11-06): 295,468 repayment obligations
(233,934 schedule rows + 61,534 card statements), 147,296 payment transactions, 386,566 banking events, 20,000 risk profiles,
3,000 financed assets; delinquency mix 75.01 / 12.00 / 6.00 / 3.99 / 3.00 %. Targets are *configurable development targets*; actual counts are in each report.
`max_account_age_months` is 24 (not 12) so that ledgers reconcile from origination and the row-count targets are met.

## 8. Validation

`python -m seed.cli validate` runs ~63 checks (SQL, scoped to one run) and fails (exit 1) on critical integrity/financial errors:

* **Structural** — constraints validated, FK integrity, product/detail consistency, completeness, reversal references, no real-looking identifiers.
* **Financial** — v1 schedules recomputed row by row; principal/markup totals; paid amounts = net allocations; allocations = payment amounts; reversals mirror originals;
  balance snapshots reconcile with ledger+allocations (windowed running sum); card statement equation, opening balance, purchases/fees/payments per cycle, finance charge recomputation; closed accounts fully satisfied.
* **Temporal** — nothing before opening or after `as_of`/closure; due-date and statement ordering; event order = occurrence order; DPD progression; and an **independent point-in-time
  recomputation of DPD and arrears for every stored delinquency snapshot** from obligations + allocations + posting dates.
* **Statistical** — product/risk/bucket distributions (target vs actual), payment behaviour, missing values, duplicates, IQR outliers (kept and classified, never deleted), scenario coverage.

`python -m seed.cli report` writes `reports/<run_id>.md|json` (counts, pass/fail, distributions, reconciliation, scenario coverage, seed, reference date, durations).

## 9. Tests

`pytest` (≈60 tests, ~15 s): financial rules with hand-derived numbers; **12 golden scenarios** (`tests/test_golden.py`, expectations written by hand — e.g. PKR 120,000 / 12 × 0% ⇒ PKR 10,000 instalments,
Aug 5 → Nov 4 = 91 DPD — never computed by the code under test); in-memory relationship/determinism/chunk-independence tests; config/URL parsing; CLI; and DB integration tests (isolated run `custom-n25-seed7…`,
removed afterwards) covering idempotent re-load, conflicting config refusal, constraint enforcement, validation, replay and every example SQL query. DB tests skip automatically if PostgreSQL is unreachable.

## 10. Replaying events

Events carry the contract `{event_id, event_type, source_system, account_id, occurred_at, recorded_at, schema_version, payload}` plus a per-account `account_sequence`.
`event_delivery_status` simulates the broker: duplicates reuse the same `event_id`; delayed deliveries arrive out of business order.

```bash
python -m seed.cli replay --account LOAN-000001 --limit 50                  # simulated delivery order (includes duplicates)
python -m seed.cli replay --order occurred --dedupe --out events.jsonl      # business order, idempotent consumer
```

## 11. Example SQL

All in [`sql/example_queries.sql`](sql/example_queries.sql) (executed by the test-suite): all overdue accounts, overdue amount by product, customers with multiple overdue accounts,
delinquency bucket distribution, accounts returning to current, payment activity by month, accounts with active collateral, recent banking events, DPD history of one account,
month-end roll-rate matrix, leakage-safe prediction labels, idempotent event replay. In `psql`: `\set run_id 'large-n10000-seed42-20261106'` and use `:'run_id'`.

```sql
SELECT p.category, count(*) AS accounts, sum(d.overdue_amount) AS overdue
FROM delinquency_snapshots d JOIN accounts a USING (account_id) JOIN products p USING (product_id)
WHERE a.run_id = :'run_id' AND d.snapshot_reason = 'AS_OF' AND d.bucket <> 'CURRENT' GROUP BY 1;
```

## 12. How this feeds the CMS

The CMS should *consume* banking data and own its operational tables. Collection cases, promises-to-pay, interactions and escalations exist as empty, `RESTRICT`-protected tables and are
deliberately **not** seeded. A CMS builds cases from `ACCOUNT_DELINQUENT` / `DELINQUENCY_BUCKET_CHANGED` events (or from `delinquency_snapshots.is_collection_eligible`), routes by `collection_teams` DPD ranges,
and closes them on `DELINQUENCY_CURED`. `delinquency_snapshots` + `repayment_schedules` + `payment_allocations` give start of delinquency, arrears evolution, partial vs full payment and cure history.

## 13. Future Kafka integration

`banking_events` is an outbox: a publisher can read rows ordered by `(account_id, account_sequence)` (per-account ordering ⇒ partition key `account_id`), emit `seed.generators.events.event_envelope(row)` and use `event_id` as the
idempotency key. The generator never touches Kafka; swapping the sink only requires a new consumer of the same rows. `recorded_at` vs `occurred_at` vs `event_delivery_status.delivered_at` model business, ingestion and broker time.

## 14. Future AI/ML

History and timestamps are preserved and snapshots contain only information available at their date. Labels must be derived from *later* observed outcomes with an explicit cutoff and window
(see `vw_roll_rate_labels`: features at a month-end cutoff, label = reaches 90+ DPD within the next 90 days). No models are trained here.

## 15. Known limitations

* Account ages reach 24 months (see §7); the history window is therefore longer than 12 months.
* Simple monthly finance charge on the unpaid billed balance (no daily-average-balance interest, no penal markup on loans, no card annual fees/cash advances).
* One restructuring per account; no re-default after restructuring; settlement/restructuring math is deliberately simplified (see §6).
* Risk profiles are two points per customer (origination and as-of); the risk score is a transparent synthetic rule, not a model.
* Holidays are an approximate synthetic list; Faker is not used (names come from fixed fictional lists so every entity is reproducible from its own RNG).
* Schedule validation reuses the generator's amortisation function for the row-by-row recomputation; independence is provided by the hand-calculated golden tests.
* Balance reconciliation is exhaustive up to 20,000 accounts and sampled (1/4) above that.
* `DATABASE_URL` in this repository's `.env` had a duplicated prefix; the loader tolerates it, but it should be corrected.

## IAM reference data (identity-access-service)

`seed/identity/` seeds the `iam` schema owned by `services/identity-access-service` (10 roles, permission catalog, role mappings,
fictional teams/scopes, optional dev-only demo users). It is idempotent and uses the IAM service's **own** database credentials
(`IAM_DATABASE_URL` or `services/identity-access-service/.env`), not this module's `DATABASE_URL`.

```bash
python -m seed.cli identity seed                 # reference data (safe everywhere)
python -m seed.cli identity seed --demo-users    # + fictional users; refuses unless the IAM APP_ENV is development/test
```

Run the IAM service's `alembic upgrade head` first. See `services/identity-access-service/README.md`.
