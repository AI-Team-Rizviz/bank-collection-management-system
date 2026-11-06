-- Example queries for the seeded Bank CMS dataset.
-- psql usage:  \set run_id 'large-n10000-seed42-20261106'   then run a query (they use :'run_id').
-- Each block starts with "-- name:" so tests/test_db_integration.py can execute them all.

-- name: all_overdue_accounts
SELECT a.account_number, p.category, d.dpd, d.bucket, d.overdue_amount, d.oldest_unpaid_due_date, d.delinquency_start_date
FROM delinquency_snapshots d
JOIN accounts a USING (account_id) JOIN products p USING (product_id)
WHERE a.run_id = :'run_id' AND d.snapshot_reason = 'AS_OF' AND d.bucket <> 'CURRENT'
ORDER BY d.dpd DESC, d.overdue_amount DESC;

-- name: overdue_amount_by_product
SELECT p.category, count(*) AS overdue_accounts, sum(d.overdue_amount) AS overdue_amount, round(avg(d.dpd), 1) AS avg_dpd
FROM delinquency_snapshots d
JOIN accounts a USING (account_id) JOIN products p USING (product_id)
WHERE a.run_id = :'run_id' AND d.snapshot_reason = 'AS_OF' AND d.bucket <> 'CURRENT'
GROUP BY p.category ORDER BY overdue_amount DESC;

-- name: customers_with_multiple_overdue_accounts
SELECT c.customer_ref, count(*) AS overdue_accounts, sum(d.overdue_amount) AS total_overdue, max(d.dpd) AS worst_dpd
FROM delinquency_snapshots d
JOIN accounts a USING (account_id) JOIN customers c USING (customer_id)
WHERE a.run_id = :'run_id' AND d.snapshot_reason = 'AS_OF' AND d.bucket <> 'CURRENT'
GROUP BY c.customer_ref HAVING count(*) > 1
ORDER BY total_overdue DESC;

-- name: delinquency_bucket_distribution
SELECT d.bucket, count(*) AS accounts, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
FROM delinquency_snapshots d JOIN accounts a USING (account_id)
WHERE a.run_id = :'run_id' AND d.snapshot_reason = 'AS_OF'
GROUP BY d.bucket ORDER BY min(d.dpd);

-- name: accounts_returning_to_current_last_30_days
SELECT a.account_number, e.occurred_at AT TIME ZONE 'Asia/Karachi' AS cured_at_pkt,
       e.payload->>'previous_bucket' AS previous_bucket, e.payload->>'cure_reason' AS cure_reason,
       (e.payload->>'days_delinquent')::int AS days_delinquent
FROM banking_events e JOIN accounts a USING (account_id)
JOIN seed_runs r ON r.run_id = a.run_id
WHERE a.run_id = :'run_id' AND e.event_type = 'DELINQUENCY_CURED' AND a.status = 'ACTIVE'
  AND e.occurred_at >= (r.as_of_date - 30)::timestamp AT TIME ZONE 'Asia/Karachi'
ORDER BY e.occurred_at DESC;

-- name: payment_activity_by_month
SELECT to_char(date_trunc('month', p.posted_at AT TIME ZONE 'Asia/Karachi'), 'YYYY-MM') AS month,
       count(*) FILTER (WHERE p.txn_type = 'PAYMENT')  AS payments,
       count(*) FILTER (WHERE p.txn_type = 'REVERSAL') AS reversals,
       sum(p.amount) FILTER (WHERE p.txn_type = 'PAYMENT')  AS paid_amount,
       sum(p.amount) FILTER (WHERE p.txn_type = 'REVERSAL') AS reversed_amount
FROM payment_transactions p JOIN accounts a USING (account_id)
WHERE a.run_id = :'run_id' AND p.status = 'POSTED'
GROUP BY 1 ORDER BY 1;

-- name: accounts_with_active_collateral
SELECT a.account_number, f.asset_category, f.make, f.model_name, f.registration_number, f.financed_amount,
       f.collateral_status, f.recovery_review_opened_on, d.dpd, d.bucket
FROM financed_assets f
JOIN accounts a USING (account_id)
JOIN delinquency_snapshots d ON d.account_id = a.account_id AND d.snapshot_reason = 'AS_OF'
WHERE a.run_id = :'run_id' AND a.status = 'ACTIVE' AND f.collateral_status IN ('LIEN_ACTIVE', 'UNDER_RECOVERY_REVIEW')
ORDER BY d.dpd DESC, f.financed_amount DESC;

-- name: recent_banking_events
SELECT e.occurred_at AT TIME ZONE 'Asia/Karachi' AS occurred_pkt, e.event_type, e.account_number, e.source_system, e.payload
FROM banking_events e JOIN accounts a USING (account_id)
WHERE a.run_id = :'run_id'
ORDER BY e.occurred_at DESC, e.account_sequence DESC
LIMIT 50;

-- name: dpd_history_of_one_account
SELECT d.snapshot_date, d.snapshot_reason, d.dpd, d.bucket, d.overdue_amount, d.overdue_obligation_count
FROM delinquency_snapshots d JOIN accounts a USING (account_id)
WHERE a.run_id = :'run_id'
  AND a.account_id = (SELECT account_id FROM delinquency_snapshots s JOIN accounts x USING (account_id)
                      WHERE x.run_id = :'run_id' AND s.bucket = 'DPD_90_PLUS' AND s.snapshot_reason = 'AS_OF' LIMIT 1)
ORDER BY d.snapshot_date, d.snapshot_reason;

-- name: roll_rate_matrix_month_end
SELECT s.bucket AS from_bucket, n.bucket AS to_bucket, count(*) AS accounts
FROM delinquency_snapshots s
JOIN delinquency_snapshots n ON n.account_id = s.account_id AND n.snapshot_reason = 'MONTH_END'
 AND n.snapshot_date = (s.snapshot_date + 1 + interval '1 month - 1 day')::date
JOIN accounts a ON a.account_id = s.account_id
WHERE a.run_id = :'run_id' AND s.snapshot_reason = 'MONTH_END'
GROUP BY 1, 2 ORDER BY 1, 2;

-- name: prediction_labels_no_leakage
-- Features come from the cutoff snapshot only; the label looks strictly AFTER the cutoff (90-day window).
SELECT l.bucket_at_cutoff, count(*) AS accounts, avg(l.reaches_90plus_within_90d::int)::numeric(6,4) AS rate_reaching_90plus
FROM vw_roll_rate_labels l JOIN accounts a USING (account_id)
WHERE a.run_id = :'run_id'
GROUP BY 1 ORDER BY 1;

-- name: replay_events_idempotently
-- First delivery of each logical event (what an idempotent consumer would process), in simulated broker order.
SELECT DISTINCT ON (e.event_id) e.event_id, e.event_type, d.delivered_at
FROM banking_events e JOIN event_delivery_status d USING (event_id) JOIN accounts a USING (account_id)
WHERE a.run_id = :'run_id'
ORDER BY e.event_id, d.attempt_no
LIMIT 20;
