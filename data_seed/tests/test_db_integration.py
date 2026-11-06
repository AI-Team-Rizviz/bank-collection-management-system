"""Integration tests against the real PostgreSQL database (skipped when it is unreachable).

They use their own isolated run (profile custom, 25 customers, seed 7) and remove only that run afterwards.
"""
import json

import pytest

from seed.config import ConfigError, load_config
from seed.database import get_engine, migrate
from seed.generators.portfolio import generate_chunks
from seed.ingestion import loader
from seed.validation.integrity import table_counts
from seed.validation.quality_report import build_report

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def db():
    try:
        engine = get_engine()
        with engine.connect():
            pass
    except (ConfigError, Exception) as exc:  # noqa: BLE001
        pytest.skip(f"database unavailable: {type(exc).__name__}")
    migrate()
    return engine


@pytest.fixture(scope="module")
def cfg():
    return load_config(profile="custom", customers=25, seed=7)


@pytest.fixture(scope="module")
def loaded(db, cfg):
    with loader.connect(db.url) as conn:
        loader.delete_run(conn, cfg.run_id)
        loader.begin_run(conn, cfg)
        generated, inserted = {}, 0
        for _, rows in generate_chunks(cfg):
            inserted += sum(loader.load_tables(conn, rows).values())
            for t, r in rows.items():
                generated[t] = generated.get(t, 0) + len(r)
        loader.finish_run(conn, cfg.run_id, 0.1)
    yield generated
    with loader.connect(db.url) as conn:
        loader.delete_run(conn, cfg.run_id)


def test_rows_loaded_match_generated(db, cfg, loaded):
    with loader.connect(db.url) as conn:
        assert loader.verify_counts(conn, cfg.run_id, loaded) == []


def test_reload_is_idempotent(db, cfg, loaded):
    with loader.connect(db.url) as conn:
        before = table_counts(conn, cfg.run_id)
        loader.begin_run(conn, cfg)
        assert sum(sum(loader.load_tables(conn, rows).values()) for _, rows in generate_chunks(cfg)) == 0
        assert table_counts(conn, cfg.run_id) == before


def test_conflicting_config_for_same_run_is_refused(db, cfg, loaded):
    clash = cfg.model_copy(update={"accounts_per_customer": 2.0})
    assert clash.run_id == cfg.run_id
    with loader.connect(db.url) as conn, pytest.raises(loader.RunConflict):
        loader.begin_run(conn, clash)


def test_quality_report_passes_with_no_critical_failures(db, cfg, loaded):
    with loader.connect(db.url) as conn:
        report = build_report(conn, cfg.run_id)
    failed = [c for c in report["checks"] if c["critical"] and not c["passed"]]
    assert failed == [] and report["passed"]
    assert report["record_counts"]["customers"] == 25


def test_database_enforces_integrity(db, cfg, loaded):
    import psycopg
    with loader.connect(db.url) as conn:
        acct = conn.execute("SELECT account_id FROM accounts WHERE run_id=%s LIMIT 1", (cfg.run_id,)).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):          # money must be positive
            conn.execute("INSERT INTO ledger_entries (entry_id, account_id, entry_type, amount, entry_date, posted_at) "
                         "VALUES (gen_random_uuid(), %s, 'FEE', -5, now(), now())", (acct,))
        conn.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):     # reversal must reference an existing original
            conn.execute("INSERT INTO payment_transactions (transaction_id, account_id, txn_type, status, amount, channel, initiated_at, "
                         "posted_at, effective_date, reverses_transaction_id, idempotency_key) VALUES (gen_random_uuid(), %s, 'REVERSAL', 'POSTED', 1, "
                         "'RAAST', now(), now(), current_date, gen_random_uuid(), 'x')", (acct,))
        conn.rollback()


def test_events_replay_and_label_view(db, cfg, loaded):
    with loader.connect(db.url) as conn:
        rows = conn.execute(
            """SELECT e.event_id, d.is_duplicate FROM banking_events e JOIN event_delivery_status d USING (event_id)
               JOIN accounts a USING (account_id) WHERE a.run_id=%s""", (cfg.run_id,)).fetchall()
        assert rows and len({r[0] for r in rows}) <= len(rows)
        conn.execute("SELECT count(*) FROM vw_roll_rate_labels").fetchone()      # view is queryable


def test_run_deletion_is_isolated(db, cfg):
    other = load_config(profile="custom", customers=5, seed=8)
    with loader.connect(db.url) as conn:
        loader.begin_run(conn, other)
        for _, rows in generate_chunks(other):
            loader.load_tables(conn, rows)
        branches_before = conn.execute("SELECT count(*) FROM branches").fetchone()[0]
        assert loader.delete_run(conn, other.run_id) == 1
        assert conn.execute("SELECT count(*) FROM accounts WHERE run_id=%s", (other.run_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM branches").fetchone()[0] == branches_before      # reference data untouched


def test_example_queries_execute(db, cfg, loaded):
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "sql" / "example_queries.sql").read_text()
    blocks = [b for b in re.split(r"^-- name: ", text, flags=re.M)[1:]]
    assert len(blocks) >= 10
    with loader.connect(db.url) as conn:
        for block in blocks:
            name, _, sql = block.partition("\n")
            sql = sql.replace(":'run_id'", "%(run_id)s")
            conn.execute(sql, {"run_id": cfg.run_id}).fetchall()
