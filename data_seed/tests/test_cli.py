import json

from typer.testing import CliRunner

from seed.cli import app

runner = CliRunner()


def test_help_lists_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("migrate", "generate", "ingest", "validate", "report", "replay", "reset-run", "run"):
        assert cmd in r.output


def test_generate_writes_inspectable_files_without_database(tmp_path):
    r = runner.invoke(app, ["generate", "--profile", "custom", "--customers", "12", "--seed", "3", "--out-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["row_counts"]["customers"] == 12
    assert (tmp_path / "accounts.jsonl").read_text().count("\n") == manifest["row_counts"]["accounts"]


def test_generate_rejects_custom_without_customer_count(tmp_path):
    assert runner.invoke(app, ["generate", "--profile", "custom", "--out-dir", str(tmp_path)]).exit_code != 0


def test_reset_run_requires_both_safety_guards():
    assert runner.invoke(app, ["reset-run", "--run-id", "x"]).exit_code == 2
    assert runner.invoke(app, ["reset-run", "--run-id", "x", "--yes-delete-run"]).exit_code == 2
    assert runner.invoke(app, ["reset-run", "--run-id", "x", "--yes-delete-run", "--confirm", "y"]).exit_code == 2
