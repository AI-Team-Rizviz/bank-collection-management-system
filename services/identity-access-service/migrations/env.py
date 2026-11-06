"""Alembic environment. Only the IAM schema is managed; the version table lives inside it."""
from alembic import context
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.domain.models import SCHEMA, Base

target_metadata = Base.metadata
VERSION_TABLE = "alembic_version_iam"


def _url() -> str:
    explicit = context.config.attributes.get("url")
    if explicit:
        return explicit
    s = get_settings()
    return s.migration_database_url or s.database_url


def _include(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return getattr(obj, "schema", None) == SCHEMA
    return True


def run() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        # Normally pre-created (owned by the migration role) by scripts/db/init_iam_roles.sql. Only attempt creation
        # when it is missing: even IF NOT EXISTS needs database-level CREATE, which the migration role should not have.
        if not conn.scalar(text("SELECT 1 FROM pg_namespace WHERE nspname = :n"), {"n": SCHEMA}):
            conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        conn.commit()
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=SCHEMA,
            include_schemas=True,
            include_object=_include,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
