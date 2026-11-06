"""Bulk, idempotent PostgreSQL loading.

Rows are COPY'd into a temp staging table and merged with INSERT ... ON CONFLICT DO NOTHING, so
re-running the same (seed, config) produces zero duplicates. Each batch is one transaction.
The same loader serves direct generation->DB mode and file ingestion (JSONL).
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

import psycopg
from sqlalchemy.engine import URL

from seed.config import GenConfig
from seed.models.tables import JSON_COLUMNS, LOAD_ORDER, metadata

BATCH_ROWS = 20_000


class RunConflict(RuntimeError):
    pass


def connect(url: URL) -> psycopg.Connection:
    return psycopg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))


def config_hash(cfg: GenConfig) -> str:
    from seed import GENERATOR_VERSION
    return hashlib.sha256((GENERATOR_VERSION + cfg.model_dump_json()).encode()).hexdigest()


def _value(col: str, v):
    if v is None:
        return None
    if col in JSON_COLUMNS and not isinstance(v, str):
        return json.dumps(v, default=str)
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v


def copy_rows(conn: psycopg.Connection, table: str, rows: list[dict]) -> int:
    """Insert rows (list of dicts) idempotently; returns the number of rows actually inserted."""
    if not rows:
        return 0
    cols = [c.name for c in metadata.tables[table].columns if c.name in rows[0]]
    col_sql = ", ".join(f'"{c}"' for c in cols)
    with conn.cursor() as cur:
        cur.execute(f'CREATE TEMP TABLE _stg (LIKE "{table}" INCLUDING DEFAULTS) ON COMMIT DROP')
        with cur.copy(f"COPY _stg ({col_sql}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row([_value(c, r.get(c)) for c in cols])
        cur.execute(f'INSERT INTO "{table}" ({col_sql}) SELECT {col_sql} FROM _stg ON CONFLICT DO NOTHING')
        n = cur.rowcount
        cur.execute("DROP TABLE _stg")
    return n


def load_tables(conn: psycopg.Connection, tables: dict[str, list[dict]]) -> dict[str, int]:
    """One transaction: insert all tables of a chunk in FK dependency order."""
    inserted: dict[str, int] = {}
    with conn.transaction():
        for t in LOAD_ORDER:
            if tables.get(t):
                inserted[t] = copy_rows(conn, t, tables[t])
    return inserted


# ------------------------------------------------------------------ run bookkeeping
def begin_run(conn: psycopg.Connection, cfg: GenConfig, generation_seconds: float | None = None) -> None:
    h = config_hash(cfg)
    with conn.transaction():
        row = conn.execute("SELECT config_hash, status FROM seed_runs WHERE run_id = %s", (cfg.run_id,)).fetchone()
        if row and row[0] != h:
            raise RunConflict(
                f"run '{cfg.run_id}' already exists with a different configuration. Use another --seed/--as-of-date/profile, "
                "or remove the old run explicitly: python -m seed.cli reset-run --run-id ... --yes-delete-run --confirm ...")
        if row:
            conn.execute("UPDATE seed_runs SET status='LOADING' WHERE run_id=%s", (cfg.run_id,))
        else:
            conn.execute(
                "INSERT INTO seed_runs (run_id, seed, profile, as_of_date, config, config_hash, generation_seconds, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'LOADING')",
                (cfg.run_id, cfg.seed, cfg.profile, cfg.as_of_date, cfg.model_dump_json(), h, generation_seconds))


def verify_counts(conn: psycopg.Connection, run_id: str, expected: dict[str, int]) -> list[str]:
    """ON CONFLICT DO NOTHING must never hide a dropped row: DB rows for this run must equal generated rows."""
    from seed.validation.integrity import GLOBAL_TABLES, table_counts
    actual = table_counts(conn, run_id)
    return [f"{t}: generated {n:,} but database holds {actual[t]:,}" for t, n in expected.items()
            if t not in GLOBAL_TABLES and actual.get(t) != n]


def finish_run(conn: psycopg.Connection, run_id: str, ingestion_seconds: float, status="LOADED") -> None:
    from seed.validation.integrity import table_counts
    counts = table_counts(conn, run_id)
    with conn.transaction():
        conn.execute(
            "UPDATE seed_runs SET status=%s, row_counts=%s, finished_at=now(), "
            "ingestion_seconds = COALESCE(ingestion_seconds,0) + %s WHERE run_id=%s",
            (status, json.dumps(counts), round(ingestion_seconds, 3), run_id))


def delete_run(conn: psycopg.Connection, run_id: str) -> int:
    with conn.transaction():
        return conn.execute("DELETE FROM seed_runs WHERE run_id = %s", (run_id,)).rowcount


# ------------------------------------------------------------------ JSONL files
class JsonlSink:
    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in self.dir.glob("*.jsonl"):
            f.unlink()
        self.counts: dict[str, int] = defaultdict(int)

    def write(self, tables: dict[str, list[dict]]) -> None:
        for t, rows in tables.items():
            with open(self.dir / f"{t}.jsonl", "a") as fh:
                for r in rows:
                    fh.write(json.dumps(r, default=str) + "\n")
            self.counts[t] += len(rows)


def read_jsonl(path: Path, batch: int = BATCH_ROWS) -> Iterator[list[dict]]:
    buf: list[dict] = []
    with open(path) as fh:
        for line in fh:
            buf.append(json.loads(line))
            if len(buf) >= batch:
                yield buf
                buf = []
    if buf:
        yield buf


def ingest_directory(conn: psycopg.Connection, directory: Path, progress=print) -> dict[str, int]:
    inserted: dict[str, int] = defaultdict(int)
    for t in LOAD_ORDER:
        path = directory / f"{t}.jsonl"
        if not path.exists():
            continue
        n_read = 0
        for rows in read_jsonl(path):
            with conn.transaction():
                inserted[t] += copy_rows(conn, t, rows)
            n_read += len(rows)
        progress(f"  {t:28s} read {n_read:>9,}  inserted {inserted[t]:>9,}")
    return dict(inserted)
