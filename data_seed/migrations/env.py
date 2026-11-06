from alembic import context
from sqlalchemy import create_engine

from seed.config import load_database_url
from seed.models.tables import metadata

target_metadata = metadata


def run_migrations_online() -> None:
    engine = create_engine(load_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
