"""users.password_hash for username/password login

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

from app.domain.models.base import SCHEMA

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column('users', 'password_hash', schema=SCHEMA)
