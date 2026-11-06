"""initial iam schema

Revision ID: 0001
Revises: 
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.domain.models.base import SCHEMA

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('access_scopes',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('scope_type', sa.String(length=16), nullable=False),
    sa.Column('scope_value', sa.String(length=64), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope_type IN ('OWN','GLOBAL') AND scope_value IS NULL) OR (scope_type NOT IN ('OWN','GLOBAL') AND scope_value ~ '^[A-Z0-9][A-Z0-9_-]{1,63}$')", name=op.f('ck_access_scopes_value_matches_type')),
    sa.CheckConstraint("scope_type IN ('OWN','TEAM','BRANCH','REGION','PORTFOLIO','GLOBAL')", name=op.f('ck_access_scopes_scope_type')),
    sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name=op.f('ck_access_scopes_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_scopes')),
    schema=SCHEMA
    )
    op.create_index('uq_access_scopes_type_value', 'access_scopes', ['scope_type', sa.literal_column("coalesce(scope_value, '')")], unique=True, schema=SCHEMA)
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_ref', sa.String(length=255), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('target_type', sa.String(length=48), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', postgresql.INET(), nullable=True),
    sa.CheckConstraint("actor_type IN ('USER','SERVICE','SYSTEM','ANONYMOUS')", name=op.f('ck_audit_logs_actor_type')),
    sa.CheckConstraint("outcome IN ('SUCCESS','DENIED','FAILURE')", name=op.f('ck_audit_logs_outcome')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs')),
    schema=SCHEMA
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False, schema=SCHEMA)
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_audit_logs_occurred_at', 'audit_logs', ['occurred_at'], unique=False, schema=SCHEMA)
    op.create_index('ix_audit_logs_target', 'audit_logs', ['target_type', 'target_id'], unique=False, schema=SCHEMA)
    op.create_table('permissions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('is_sensitive', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('allowed_scope_types', postgresql.ARRAY(sa.String(length=16)), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("allowed_scope_types IS NULL OR allowed_scope_types <@ ARRAY['OWN','TEAM','BRANCH','REGION','PORTFOLIO','GLOBAL']::varchar[]", name=op.f('ck_permissions_scope_types')),
    sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'", name=op.f('ck_permissions_code_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permissions')),
    sa.UniqueConstraint('code', name=op.f('uq_permissions_code')),
    schema=SCHEMA
    )
    op.create_table('roles',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_privileged', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('phase', sa.String(length=8), server_default='MVP', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{2,63}$'", name=op.f('ck_roles_code_format')),
    sa.CheckConstraint("phase IN ('MVP','FUTURE')", name=op.f('ck_roles_phase')),
    sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name=op.f('ck_roles_status')),
    sa.CheckConstraint('NOT (is_privileged AND NOT is_system)', name=op.f('ck_roles_privileged_implies_system')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('code', name=op.f('uq_roles_code')),
    schema=SCHEMA
    )
    op.create_table('teams',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.String(length=64), nullable=True),
    sa.Column('region_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{1,63}$'", name=op.f('ck_teams_code_format')),
    sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name=op.f('ck_teams_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_teams')),
    sa.UniqueConstraint('code', name=op.f('uq_teams_code')),
    schema=SCHEMA
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('external_identity_id', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('authz_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("email = lower(email) AND position('@' in email) > 1", name=op.f('ck_users_email_format')),
    sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name=op.f('ck_users_status')),
    sa.CheckConstraint("username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'", name=op.f('ck_users_username_format')),
    sa.ForeignKeyConstraint(['created_by'], ['iam.users.id'], name=op.f('fk_users_created_by_users')),
    sa.ForeignKeyConstraint(['updated_by'], ['iam.users.id'], name=op.f('fk_users_updated_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('external_identity_id', name=op.f('uq_users_external_identity_id')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username')),
    schema=SCHEMA
    )
    op.create_index('ix_users_status', 'users', ['status'], unique=False, schema=SCHEMA)
    op.create_table('access_requests',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('request_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='PENDING', nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('target_user_id', sa.UUID(), nullable=True),
    sa.Column('role_id', sa.UUID(), nullable=True),
    sa.Column('permission_id', sa.UUID(), nullable=True),
    sa.Column('scope_id', sa.UUID(), nullable=True),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('justification', sa.Text(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_reason', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(request_type = 'ASSIGN_ROLE' AND target_user_id IS NOT NULL AND role_id IS NOT NULL   AND permission_id IS NULL AND scope_id IS NULL) OR (request_type = 'GRANT_SCOPE' AND target_user_id IS NOT NULL AND scope_id IS NOT NULL   AND role_id IS NULL AND permission_id IS NULL) OR (request_type IN ('GRANT_ROLE_PERMISSION','REVOKE_ROLE_PERMISSION') AND role_id IS NOT NULL   AND permission_id IS NOT NULL AND target_user_id IS NULL AND scope_id IS NULL)", name=op.f('ck_access_requests_shape_matches_type')),
    sa.CheckConstraint("status IN ('PENDING','APPLIED','REJECTED','FAILED')", name=op.f('ck_access_requests_status')),
    sa.ForeignKeyConstraint(['permission_id'], ['iam.permissions.id'], name=op.f('fk_access_requests_permission_id_permissions')),
    sa.ForeignKeyConstraint(['requested_by'], ['iam.users.id'], name=op.f('fk_access_requests_requested_by_users')),
    sa.ForeignKeyConstraint(['role_id'], ['iam.roles.id'], name=op.f('fk_access_requests_role_id_roles')),
    sa.ForeignKeyConstraint(['scope_id'], ['iam.access_scopes.id'], name=op.f('fk_access_requests_scope_id_access_scopes')),
    sa.ForeignKeyConstraint(['target_user_id'], ['iam.users.id'], name=op.f('fk_access_requests_target_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_requests')),
    schema=SCHEMA
    )
    op.create_index('ix_access_requests_requested_by', 'access_requests', ['requested_by'], unique=False, schema=SCHEMA)
    op.create_index('ix_access_requests_status', 'access_requests', ['status'], unique=False, schema=SCHEMA)
    op.create_table('role_conflicts',
    sa.Column('role_a_id', sa.UUID(), nullable=False),
    sa.Column('role_b_id', sa.UUID(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.CheckConstraint('role_a_id < role_b_id', name=op.f('ck_role_conflicts_ordered_pair')),
    sa.ForeignKeyConstraint(['role_a_id'], ['iam.roles.id'], name=op.f('fk_role_conflicts_role_a_id_roles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_b_id'], ['iam.roles.id'], name=op.f('fk_role_conflicts_role_b_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_a_id', 'role_b_id', name=op.f('pk_role_conflicts')),
    schema=SCHEMA
    )
    op.create_table('role_permissions',
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('permission_id', sa.UUID(), nullable=False),
    sa.Column('granted_by', sa.UUID(), nullable=True),
    sa.Column('source_request_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['iam.permissions.id'], name=op.f('fk_role_permissions_permission_id_permissions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['iam.roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id', name=op.f('pk_role_permissions')),
    schema=SCHEMA
    )
    op.create_index('ix_role_permissions_permission_id', 'role_permissions', ['permission_id'], unique=False, schema=SCHEMA)
    op.create_table('team_members',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('member_role', sa.String(length=16), server_default='MEMBER', nullable=False),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('added_by', sa.UUID(), nullable=True),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("member_role IN ('LEAD','MEMBER')", name=op.f('ck_team_members_member_role')),
    sa.CheckConstraint("status IN ('ACTIVE','REMOVED')", name=op.f('ck_team_members_status')),
    sa.ForeignKeyConstraint(['team_id'], ['iam.teams.id'], name=op.f('fk_team_members_team_id_teams')),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_team_members_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_team_members')),
    schema=SCHEMA
    )
    op.create_index('ix_team_members_user_id', 'team_members', ['user_id'], unique=False, schema=SCHEMA)
    op.create_index('uq_team_members_active', 'team_members', ['team_id', 'user_id'], unique=True, schema=SCHEMA, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_table('user_access_scopes',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('scope_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('granted_by', sa.UUID(), nullable=True),
    sa.Column('source_request_id', sa.UUID(), nullable=True),
    sa.Column('revoked_by', sa.UUID(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name=op.f('ck_user_access_scopes_status')),
    sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name=op.f('ck_user_access_scopes_validity_window')),
    sa.ForeignKeyConstraint(['scope_id'], ['iam.access_scopes.id'], name=op.f('fk_user_access_scopes_scope_id_access_scopes')),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_user_access_scopes_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_access_scopes')),
    schema=SCHEMA
    )
    op.create_index('ix_user_access_scopes_user_id', 'user_access_scopes', ['user_id'], unique=False, schema=SCHEMA)
    op.create_index('uq_user_access_scopes_active', 'user_access_scopes', ['user_id', 'scope_id'], unique=True, schema=SCHEMA, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_table('user_roles',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assigned_by', sa.UUID(), nullable=True),
    sa.Column('source_request_id', sa.UUID(), nullable=True),
    sa.Column('revoked_by', sa.UUID(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name=op.f('ck_user_roles_status')),
    sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name=op.f('ck_user_roles_validity_window')),
    sa.ForeignKeyConstraint(['role_id'], ['iam.roles.id'], name=op.f('fk_user_roles_role_id_roles')),
    sa.ForeignKeyConstraint(['user_id'], ['iam.users.id'], name=op.f('fk_user_roles_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_roles')),
    schema=SCHEMA
    )
    op.create_index('ix_user_roles_role_id', 'user_roles', ['role_id'], unique=False, schema=SCHEMA)
    op.create_index('ix_user_roles_user_id', 'user_roles', ['user_id'], unique=False, schema=SCHEMA)
    op.create_index('uq_user_roles_active', 'user_roles', ['user_id', 'role_id'], unique=True, schema=SCHEMA, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_table('access_approvals',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('approver_id', sa.UUID(), nullable=False),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('APPROVED','REJECTED')", name=op.f('ck_access_approvals_decision')),
    sa.ForeignKeyConstraint(['approver_id'], ['iam.users.id'], name=op.f('fk_access_approvals_approver_id_users')),
    sa.ForeignKeyConstraint(['request_id'], ['iam.access_requests.id'], name=op.f('fk_access_approvals_request_id_access_requests')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_approvals')),
    sa.UniqueConstraint('request_id', 'approver_id', name='uq_access_approvals_request_approver'),
    schema=SCHEMA
    )
    op.create_index('ix_access_approvals_approver_id', 'access_approvals', ['approver_id'], unique=False, schema=SCHEMA)

    # --- audit_logs is append-only: reject UPDATE/DELETE for every role (incl. the owner) -----------------
    op.execute(f"""
        CREATE FUNCTION "{SCHEMA}".audit_logs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only' USING ERRCODE = 'insufficient_privilege';
        END $$""")
    op.execute(f"""
        CREATE TRIGGER audit_logs_no_update_delete BEFORE UPDATE OR DELETE ON "{SCHEMA}".audit_logs
        FOR EACH ROW EXECUTE FUNCTION "{SCHEMA}".audit_logs_immutable()""")
    # Narrow the runtime role (if it exists) to what an append-only log needs.
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'iam_user') THEN
            REVOKE ALL ON "{SCHEMA}".audit_logs FROM iam_user;
            GRANT SELECT, INSERT ON "{SCHEMA}".audit_logs TO iam_user;
            GRANT USAGE, SELECT ON SEQUENCE "{SCHEMA}".audit_logs_id_seq TO iam_user;
          END IF;
        END $$""")


def downgrade() -> None:
    op.execute(f'DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON "{SCHEMA}".audit_logs')
    op.execute(f'DROP FUNCTION IF EXISTS "{SCHEMA}".audit_logs_immutable()')
    op.drop_index('ix_access_approvals_approver_id', table_name='access_approvals', schema=SCHEMA)
    op.drop_table('access_approvals', schema=SCHEMA)
    op.drop_index('uq_user_roles_active', table_name='user_roles', schema=SCHEMA, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.drop_index('ix_user_roles_user_id', table_name='user_roles', schema=SCHEMA)
    op.drop_index('ix_user_roles_role_id', table_name='user_roles', schema=SCHEMA)
    op.drop_table('user_roles', schema=SCHEMA)
    op.drop_index('uq_user_access_scopes_active', table_name='user_access_scopes', schema=SCHEMA, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.drop_index('ix_user_access_scopes_user_id', table_name='user_access_scopes', schema=SCHEMA)
    op.drop_table('user_access_scopes', schema=SCHEMA)
    op.drop_index('uq_team_members_active', table_name='team_members', schema=SCHEMA, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.drop_index('ix_team_members_user_id', table_name='team_members', schema=SCHEMA)
    op.drop_table('team_members', schema=SCHEMA)
    op.drop_index('ix_role_permissions_permission_id', table_name='role_permissions', schema=SCHEMA)
    op.drop_table('role_permissions', schema=SCHEMA)
    op.drop_table('role_conflicts', schema=SCHEMA)
    op.drop_index('ix_access_requests_status', table_name='access_requests', schema=SCHEMA)
    op.drop_index('ix_access_requests_requested_by', table_name='access_requests', schema=SCHEMA)
    op.drop_table('access_requests', schema=SCHEMA)
    op.drop_index('ix_users_status', table_name='users', schema=SCHEMA)
    op.drop_table('users', schema=SCHEMA)
    op.drop_table('teams', schema=SCHEMA)
    op.drop_table('roles', schema=SCHEMA)
    op.drop_table('permissions', schema=SCHEMA)
    op.drop_index('ix_audit_logs_target', table_name='audit_logs', schema=SCHEMA)
    op.drop_index('ix_audit_logs_occurred_at', table_name='audit_logs', schema=SCHEMA)
    op.drop_index('ix_audit_logs_actor_user_id', table_name='audit_logs', schema=SCHEMA)
    op.drop_index('ix_audit_logs_action', table_name='audit_logs', schema=SCHEMA)
    op.drop_table('audit_logs', schema=SCHEMA)
    op.drop_index('uq_access_scopes_type_value', table_name='access_scopes', schema=SCHEMA)
    op.drop_table('access_scopes', schema=SCHEMA)
