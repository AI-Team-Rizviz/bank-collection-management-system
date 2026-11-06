"""Engine creation, connectivity check and Alembic migration runner."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from seed.config import PROJECT_ROOT, load_database_url, redact


def get_engine(**kw) -> Engine:
    return create_engine(load_database_url(), pool_pre_ping=True, **kw)


def check_connection(engine: Engine) -> str:
    with engine.connect() as conn:
        version = conn.execute(text("select version()")).scalar_one()
    return f"{redact(engine.url)} -> {version.split(',')[0]}"


def alembic_config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(PROJECT_ROOT / "migrations")))
    return cfg


def migrate(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)
