"""Idempotency keys are unique per account (not globally), so several seed runs can coexist.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE payment_transactions DROP CONSTRAINT uq_payment_transactions_idempotency_key")
    op.execute("ALTER TABLE payment_transactions ADD CONSTRAINT uq_payment_transactions_acct_key UNIQUE (account_id, idempotency_key)")


def downgrade() -> None:
    op.execute("ALTER TABLE payment_transactions DROP CONSTRAINT uq_payment_transactions_acct_key")
    op.execute("ALTER TABLE payment_transactions ADD CONSTRAINT uq_payment_transactions_idempotency_key UNIQUE (idempotency_key)")
