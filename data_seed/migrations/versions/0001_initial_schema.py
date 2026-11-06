"""Initial schema: master data, servicing, risk, events and CMS-owned tables.

Revision ID: 0001
Revises:
"""
from alembic import op

from migrations.schema_0001 import metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Illustrative, leakage-safe label view: features come from the snapshot at the cutoff only;
# the label looks strictly AFTER the cutoff, inside a 90-day outcome window.
LABEL_VIEW = """
CREATE VIEW vw_roll_rate_labels AS
SELECT s.account_id,
       s.snapshot_date            AS prediction_cutoff,
       s.dpd                      AS dpd_at_cutoff,
       s.bucket                   AS bucket_at_cutoff,
       s.overdue_amount           AS overdue_at_cutoff,
       EXISTS (SELECT 1 FROM delinquency_snapshots f
                WHERE f.account_id = s.account_id
                  AND f.snapshot_date >  s.snapshot_date
                  AND f.snapshot_date <= s.snapshot_date + 90
                  AND f.bucket = 'DPD_90_PLUS')            AS reaches_90plus_within_90d
FROM delinquency_snapshots s
JOIN accounts a ON a.account_id = s.account_id
JOIN seed_runs r ON r.run_id = a.run_id
WHERE s.snapshot_reason = 'MONTH_END'
  AND s.snapshot_date + 90 <= r.as_of_date
"""


def upgrade() -> None:
    # Materialises the FROZEN schema snapshot in migrations/schema_0001.py. Later changes are separate migrations.
    metadata.create_all(op.get_bind(), checkfirst=False)
    op.execute(LABEL_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vw_roll_rate_labels")
    metadata.drop_all(op.get_bind())
