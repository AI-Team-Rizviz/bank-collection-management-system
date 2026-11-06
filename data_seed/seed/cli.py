"""Command line interface:  python -m seed.cli --help"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import typer

from seed.config import PROJECT_ROOT, ConfigError, GenConfig, load_config, redact
from seed.database import check_connection, get_engine, migrate as run_migrations
from seed.ingestion import loader

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Synthetic banking data generator & PostgreSQL seeder.")

ConfigOpt = typer.Option(None, "--config", help="TOML config file (see seed.config.example.toml).")
ProfileOpt = typer.Option("small", help="small (100) | medium (1,000) | large (10,000) | custom")


def _cfg(config: Path | None, profile: str, customers: int | None, seed: int | None, as_of_date: str | None) -> GenConfig:
    try:
        return load_config(config, profile=profile, customers=customers, seed=seed,
                           as_of_date=date.fromisoformat(as_of_date) if as_of_date else None)
    except (ConfigError, ValueError) as exc:
        typer.secho(f"Configuration error: {exc}", fg="red", err=True)
        raise typer.Exit(2)


def _engine():
    try:
        eng = get_engine()
        typer.echo("Database: " + check_connection(eng))
        return eng
    except ConfigError as exc:
        typer.secho(f"Configuration error: {exc}", fg="red", err=True)
        raise typer.Exit(2)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Database connection failed: {type(exc).__name__} (credentials are never printed).", fg="red", err=True)
        raise typer.Exit(3)


def _latest_run(conn) -> str:
    row = conn.execute("SELECT run_id FROM seed_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        typer.secho("No runs found. Run `generate` + `ingest` (or `run`) first.", fg="red", err=True)
        raise typer.Exit(1)
    return row[0]


@app.command()
def migrate(revision: str = "head") -> None:
    """Apply Alembic migrations."""
    _engine()
    run_migrations(revision)
    typer.echo(f"Migrations applied up to '{revision}'.")


@app.command("check-db")
def check_db() -> None:
    """Verify DATABASE_URL and connectivity (password is never shown)."""
    _engine()


@app.command()
def generate(profile: str = ProfileOpt, customers: Optional[int] = typer.Option(None, help="Customer count (custom profile)"),
             seed: int = typer.Option(42), as_of_date: Optional[str] = typer.Option(None, help="YYYY-MM-DD (default 2026-11-06)"),
             config: Optional[Path] = ConfigOpt, out_dir: Optional[Path] = typer.Option(None, help="Default: data/<run_id>")) -> None:
    """Generate a dataset to JSONL files (no database needed) for inspection before ingestion."""
    cfg = _cfg(config, profile, customers, seed, as_of_date)
    from seed.generators.portfolio import generate_chunks
    out = out_dir or PROJECT_ROOT / "data" / cfg.run_id
    sink = loader.JsonlSink(out)
    t0 = time.perf_counter()
    for i, (name, rows) in enumerate(generate_chunks(cfg), start=1):
        sink.write(rows)
        typer.echo(f"  {name}: {sum(len(v) for v in rows.values()):,} rows")
    secs = round(time.perf_counter() - t0, 3)
    (out / "manifest.json").write_text(json.dumps(dict(run_id=cfg.run_id, config=json.loads(cfg.model_dump_json()),
                                                       generation_seconds=secs, row_counts=dict(sink.counts)), indent=2))
    typer.echo(f"Run '{cfg.run_id}' written to {out} in {secs}s")
    for t, n in sink.counts.items():
        typer.echo(f"  {t:28s} {n:>10,}")


@app.command()
def ingest(directory: Path = typer.Argument(None, help="Generated directory (default: latest data/*)"),
           run_id: Optional[str] = typer.Option(None, help="Run id (looks in data/<run_id>)")) -> None:
    """Load a generated directory into PostgreSQL (idempotent; re-running inserts nothing new)."""
    d = directory or (PROJECT_ROOT / "data" / run_id if run_id else None)
    if d is None:
        cands = sorted((PROJECT_ROOT / "data").glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
        if not cands:
            typer.secho("No generated data found; run `generate` first.", fg="red", err=True)
            raise typer.Exit(1)
        d = cands[-1].parent
    manifest = json.loads((d / "manifest.json").read_text())
    cfg = GenConfig(**manifest["config"])
    eng = _engine()
    t0 = time.perf_counter()
    with loader.connect(eng.url) as conn:
        try:
            loader.begin_run(conn, cfg, manifest.get("generation_seconds"))
        except loader.RunConflict as exc:
            typer.secho(str(exc), fg="red", err=True)
            raise typer.Exit(4)
        try:
            inserted = loader.ingest_directory(conn, d, typer.echo)
        except Exception:
            loader.finish_run(conn, cfg.run_id, time.perf_counter() - t0, status="FAILED")
            raise
        problems = loader.verify_counts(conn, cfg.run_id, manifest["row_counts"])
        if problems:
            loader.finish_run(conn, cfg.run_id, time.perf_counter() - t0, status="FAILED")
            typer.secho("Row-count verification FAILED (rows were silently skipped):\n  " + "\n  ".join(problems), fg="red", err=True)
            raise typer.Exit(5)
        loader.finish_run(conn, cfg.run_id, time.perf_counter() - t0)
    typer.echo(f"Ingested run '{cfg.run_id}': {sum(inserted.values()):,} new rows in {time.perf_counter() - t0:.1f}s")


@app.command()
def run(profile: str = ProfileOpt, customers: Optional[int] = typer.Option(None), seed: int = typer.Option(42),
        as_of_date: Optional[str] = typer.Option(None), config: Optional[Path] = ConfigOpt,
        skip_validate: bool = typer.Option(False, help="Skip validation/report after loading")) -> None:
    """Direct mode: migrate -> generate and load chunk by chunk (bounded memory) -> validate -> report."""
    cfg = _cfg(config, profile, customers, seed, as_of_date)
    eng = _engine()
    run_migrations()
    from seed.generators.portfolio import build_portfolio, generate_chunks
    gen_s = ing_s = 0.0
    with loader.connect(eng.url) as conn:
        try:
            loader.begin_run(conn, cfg)
        except loader.RunConflict as exc:
            typer.secho(str(exc), fg="red", err=True)
            raise typer.Exit(4)
        t = time.perf_counter()
        pf = build_portfolio(cfg)
        gen_s += time.perf_counter() - t
        it = generate_chunks(cfg, pf)
        total, generated = 0, {}
        while True:
            t = time.perf_counter()
            try:
                name, rows = next(it)
            except StopIteration:
                break
            gen_s += time.perf_counter() - t
            t = time.perf_counter()
            inserted = loader.load_tables(conn, rows)
            ing_s += time.perf_counter() - t
            total += sum(inserted.values())
            for t_, rows_ in rows.items():
                generated[t_] = generated.get(t_, 0) + len(rows_)
            typer.echo(f"  {name}: loaded {sum(inserted.values()):,} new rows")
        conn.execute("UPDATE seed_runs SET generation_seconds=%s, ingestion_seconds=0 WHERE run_id=%s", (round(gen_s, 3), cfg.run_id))
        conn.commit()
        problems = loader.verify_counts(conn, cfg.run_id, generated)
        if problems:
            loader.finish_run(conn, cfg.run_id, ing_s, status="FAILED")
            typer.secho("Row-count verification FAILED (rows were silently skipped):\n  " + "\n  ".join(problems), fg="red", err=True)
            raise typer.Exit(5)
        loader.finish_run(conn, cfg.run_id, ing_s)
    typer.echo(f"Run '{cfg.run_id}' loaded: {total:,} new rows (generation {gen_s:.1f}s, ingestion {ing_s:.1f}s)")
    if not skip_validate:
        _validate_and_report(eng, cfg.run_id, write=True)


def _validate_and_report(eng, run_id: str, write: bool) -> bool:
    from seed.validation.quality_report import build_report, write_report
    with loader.connect(eng.url) as conn:
        r = build_report(conn, run_id)
    for c in r["checks"]:
        if not c["passed"]:
            typer.secho(f"  {'FAIL' if c['critical'] else 'WARN'}  {c['name']}: {c['detail']}", fg="red" if c["critical"] else "yellow")
    s = r["summary"]
    typer.secho(f"Validation {'PASSED' if r['passed'] else 'FAILED'}: {s['passed']}/{s['total']} checks, "
                f"{s['critical_failures']} critical failures, {s['soft_warnings']} warnings",
                fg="green" if r["passed"] else "red")
    if write:
        jp, mp = write_report(r)
        typer.echo(f"Report: {mp}  (+ {jp.name})")
    return r["passed"]


@app.command()
def validate(run_id: Optional[str] = typer.Option(None, help="Default: most recent run")) -> None:
    """Run all data-quality checks; exit code 1 on critical integrity/financial failures."""
    eng = _engine()
    with loader.connect(eng.url) as conn:
        rid = run_id or _latest_run(conn)
    if not _validate_and_report(eng, rid, write=False):
        raise typer.Exit(1)


@app.command()
def report(run_id: Optional[str] = typer.Option(None), out_dir: Optional[Path] = typer.Option(None)) -> None:
    """Write the data-quality report (Markdown + JSON) to reports/."""
    from seed.validation.quality_report import build_report, write_report
    eng = _engine()
    with loader.connect(eng.url) as conn:
        r = build_report(conn, run_id or _latest_run(conn))
    jp, mp = write_report(r, out_dir)
    typer.echo(f"Report written: {mp}\nResult: {'PASS' if r['passed'] else 'FAIL'}")
    if not r["passed"]:
        raise typer.Exit(1)


@app.command("list-runs")
def list_runs() -> None:
    """List loaded seed runs."""
    eng = _engine()
    with loader.connect(eng.url) as conn:
        for r in conn.execute("SELECT run_id, status, seed, as_of_date, created_at FROM seed_runs ORDER BY created_at"):
            typer.echo(f"{r[0]:50s} {r[1]:8s} seed={r[2]} as_of={r[3]} created={r[4]:%Y-%m-%d %H:%M}")


@app.command()
def replay(run_id: Optional[str] = typer.Option(None), account: Optional[str] = typer.Option(None, help="Account number, e.g. LOAN-000001"),
           order: str = typer.Option("delivery", help="delivery (simulated broker order, incl. duplicates/delays) | occurred (business order)"),
           dedupe: bool = typer.Option(False, help="Drop repeated deliveries of the same event_id (idempotent consumer)"),
           limit: int = typer.Option(20), out: Optional[Path] = typer.Option(None, help="Write JSONL here instead of stdout")) -> None:
    """Replay stored banking events as JSON envelopes, ready for a future Kafka producer."""
    from seed.generators.events import event_envelope
    eng = _engine()
    with loader.connect(eng.url) as conn:
        rid = run_id or _latest_run(conn)
        sort = "d.delivered_at, e.event_id, d.attempt_no" if order == "delivery" else "e.occurred_at, e.account_sequence, d.attempt_no"
        cur = conn.execute(
            f"""SELECT e.event_id, e.event_type, e.source_system, e.account_number, e.occurred_at, e.recorded_at, e.schema_version, e.payload, d.is_duplicate
                FROM banking_events e JOIN event_delivery_status d USING (event_id) JOIN accounts a USING (account_id)
                WHERE a.run_id=%s {"AND a.account_number=%s" if account else ""} ORDER BY {sort} LIMIT %s""",
            (rid, account, limit) if account else (rid, limit))
        seen, fh, n = set(), open(out, "w") if out else sys.stdout, 0
        for eid, et, src, acct, occ, rec, ver, payload, dup in cur:
            if dedupe and eid in seen:
                continue
            seen.add(eid)
            row = dict(event_id=eid, event_type=et, source_system=src, account_number=acct, occurred_at=occ, recorded_at=rec,
                       schema_version=ver, payload=payload)
            env = event_envelope(row)
            env["occurred_at"], env["recorded_at"] = occ.astimezone(__import__("seed.simulation.timeline", fromlist=["KARACHI"]).KARACHI).isoformat(), \
                rec.astimezone(__import__("seed.simulation.timeline", fromlist=["KARACHI"]).KARACHI).isoformat()
            env["delivery_is_duplicate"] = dup
            fh.write(json.dumps(env, default=str) + "\n")
            n += 1
        if out:
            fh.close()
            typer.echo(f"{n} events written to {out}")


@app.command("reset-run")
def reset_run(run_id: str = typer.Option(..., help="Run to delete"),
              yes_delete_run: bool = typer.Option(False, "--yes-delete-run", help="Required safety flag"),
              confirm: str = typer.Option("", help="Type the run id again to confirm")) -> None:
    """Delete ONE seeded run (cascades to its customers/accounts/events). Never touches other runs, reference
    data or CMS tables; refuses if CMS records (cases etc.) reference the run's accounts."""
    if not yes_delete_run or confirm != run_id:
        typer.secho("Refusing: pass --yes-delete-run and --confirm <exact run id>.", fg="red", err=True)
        raise typer.Exit(2)
    eng = _engine()
    with loader.connect(eng.url) as conn:
        try:
            n = loader.delete_run(conn, run_id)
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"Delete blocked: {type(exc).__name__} (CMS records may reference this run).", fg="red", err=True)
            raise typer.Exit(1)
    typer.echo(f"Deleted run '{run_id}'." if n else f"Run '{run_id}' not found.")


if __name__ == "__main__":
    app()
