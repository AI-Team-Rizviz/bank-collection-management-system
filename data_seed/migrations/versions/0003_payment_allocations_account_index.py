"""Index payment_allocations by account (ledger reconciliation and CMS account-level queries).

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_allocations_account ON payment_allocations (account_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_allocations_account")
