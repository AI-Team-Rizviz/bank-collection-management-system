import pytest

from seed.config import ConfigError, load_config, load_database_url, redact


def write_env(tmp_path, value):
    p = tmp_path / ".env"
    p.write_text(f"DATABASE_URL={value}\n")
    return p


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_plain_url(tmp_path):
    url = load_database_url(write_env(tmp_path, "postgresql://u:p%40ss%24@localhost:5432/bank-cms"))
    assert (url.drivername, url.host, url.port, url.database, url.username) == ("postgresql+psycopg", "localhost", 5432, "bank-cms", "u")
    assert url.password == "p@ss$"                       # URL-encoded special characters are decoded


def test_dollar_sign_is_not_interpolated(tmp_path):
    assert load_database_url(write_env(tmp_path, "postgresql://u:abc$def@h/db")).password == "abc$def"


def test_duplicated_prefix_is_tolerated_with_warning(tmp_path, capsys):
    url = load_database_url(write_env(tmp_path, "DATABASE_URL=postgresql://u:secret@h:5432/db"))
    assert url.host == "h"
    out = capsys.readouterr().out
    assert "extra 'DATABASE_URL='" in out and "secret" not in out


def test_missing_and_bad_scheme(tmp_path):
    with pytest.raises(ConfigError):
        load_database_url(tmp_path / "missing.env")
    with pytest.raises(ConfigError):
        load_database_url(write_env(tmp_path, "mysql://u:p@h/db"))


def test_redact_hides_password(tmp_path):
    assert "secret" not in redact(load_database_url(write_env(tmp_path, "postgresql://u:secret@h/db")))


def test_profiles_and_run_id():
    assert load_config(profile="small").n_customers == 100
    assert load_config(profile="large").n_customers == 10_000 and load_config(profile="large").n_accounts == 15_000
    assert load_config(profile="custom", customers=7).n_customers == 7
    assert load_config(profile="small", seed=1).run_id != load_config(profile="small", seed=2).run_id


def test_delinquency_mix_must_sum_to_one():
    with pytest.raises(ValueError):
        load_config(profile="small", delinquency=dict(current=0.5))
