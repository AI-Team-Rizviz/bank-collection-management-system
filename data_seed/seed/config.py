"""Configuration: database URL handling and the synthetic-data generation config.

All product terms, rates, thresholds and the delinquency mix below are SYNTHETIC test
assumptions. They are not Allied Bank Pakistan (or any bank's) actual policy.
"""
from __future__ import annotations

import os
import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PREFIX = "DATABASE_URL="


class ConfigError(ValueError):
    pass


# --------------------------------------------------------------------------- database url
def _read_env_file(path: Path) -> dict[str, str]:
    """Minimal .env reader with NO variable interpolation (a '$' in a password is literal)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_database_url(env_file: Path | None = None) -> URL:
    """Resolve DATABASE_URL (process env first, then .env) into a SQLAlchemy URL for psycopg 3.

    A duplicated "DATABASE_URL=" prefix inside the value is tolerated with a warning (no secret is
    printed). The password may contain URL-encoded characters.
    """
    raw = os.environ.get("DATABASE_URL") or _read_env_file(env_file or PROJECT_ROOT / ".env").get(
        "DATABASE_URL"
    )
    if not raw:
        raise ConfigError("DATABASE_URL is not set (environment or .env). See .env.example.")
    stripped = 0
    while raw.startswith(_PREFIX):
        raw = raw[len(_PREFIX):]
        stripped += 1
    if stripped:
        print(
            f"WARNING: DATABASE_URL value contained {stripped} extra 'DATABASE_URL=' prefix(es); "
            "ignored. Please fix your .env (one assignment only).",
        )
    for scheme in ("postgresql://", "postgres://"):
        if raw.startswith(scheme):
            raw = "postgresql+psycopg://" + raw[len(scheme):]
    try:
        url = make_url(raw)
    except Exception as exc:  # noqa: BLE001 - never echo the raw string (it holds a password)
        raise ConfigError("DATABASE_URL is not a valid URL (check URL-encoding of the password).") from exc
    if url.drivername != "postgresql+psycopg":
        raise ConfigError("DATABASE_URL must use the postgresql:// scheme.")
    if not url.host or not url.database:
        raise ConfigError("DATABASE_URL must include host and database name.")
    return url


def redact(url: URL) -> str:
    return url.render_as_string(hide_password=True)


# --------------------------------------------------------------------------- generation config
PROFILES = {"small": 100, "medium": 1_000, "large": 10_000}


class DelinquencyMix(BaseModel):
    """Target share of ACCOUNTS per delinquency bucket at as_of (synthetic assumption)."""

    current: float = 0.75
    dpd_1_30: float = 0.12
    dpd_31_60: float = 0.06
    dpd_61_90: float = 0.04
    dpd_90_plus: float = 0.03

    @model_validator(mode="after")
    def _sums_to_one(self) -> "DelinquencyMix":
        total = self.current + self.dpd_1_30 + self.dpd_31_60 + self.dpd_61_90 + self.dpd_90_plus
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"delinquency mix must sum to 1.0 (got {total})")
        return self


class ProductMix(BaseModel):
    """Share of accounts per product (15,000 accounts -> 6,000 / 6,000 / 3,000)."""

    personal_loan: float = 0.40
    credit_card: float = 0.40
    asset_financing: float = 0.20


class PolicyConfig(BaseModel):
    """Synthetic servicing / delinquency policy. NOT a real bank's policy."""

    policy_version: str = "SYN-POLICY-v1"
    grace_days: int = 0                      # delinquent when DPD > grace_days
    tolerance: Decimal = Decimal("1.00")     # shortfalls <= this (PKR) are treated as paid
    collection_min_dpd: int = 1              # collection eligibility: DPD >= this ...
    collection_min_overdue: Decimal = Decimal("500.00")  # ... and overdue >= this
    # personal loan (reducing balance)
    loan_rate_range: tuple[float, float] = (18.0, 30.0)
    loan_terms: tuple[int, ...] = (6, 12, 18, 24, 36, 48, 60)
    loan_term_weights: tuple[float, ...] = (0.05, 0.25, 0.10, 0.30, 0.20, 0.07, 0.03)
    loan_principal_range: tuple[int, int] = (50_000, 2_500_000)
    # asset financing (flat rate)
    asset_rate_range: tuple[float, float] = (14.0, 22.0)
    asset_terms: tuple[int, ...] = (12, 18, 24, 36, 48)
    asset_term_weights: tuple[float, ...] = (0.15, 0.10, 0.35, 0.30, 0.10)
    asset_down_payment_pct: tuple[float, float] = (0.15, 0.40)
    # credit card
    card_statement_due_days: int = 21
    card_min_pct: Decimal = Decimal("5.00")
    card_min_floor: Decimal = Decimal("500.00")
    card_monthly_finance_rate: Decimal = Decimal("3.50")  # % per month on unpaid billed balance
    card_late_fee: Decimal = Decimal("1500.00")
    card_block_dpd: int = 30                 # DPD above this -> TEMPORARY_BLOCK (no new purchases)
    card_suspend_dpd: int = 60               # DPD above this -> SUSPENDED
    recovery_review_dpd: int = 90            # asset: DPD above this -> collateral recovery review
    repossession_dpd: int = 150


class GenConfig(BaseModel):
    seed: int = 42
    profile: str = "small"
    customers: int | None = None
    accounts_per_customer: float = 1.5
    as_of_date: date = date(2026, 11, 6)
    business_timezone: str = "Asia/Karachi"
    currency: str = "PKR"
    max_account_age_months: int = 24
    min_account_age_days: int = 35
    chunk_customers: int = 500
    delinquency: DelinquencyMix = Field(default_factory=DelinquencyMix)
    products: ProductMix = Field(default_factory=ProductMix)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    # event-delivery simulation
    duplicate_delivery_rate: float = 0.015
    delayed_delivery_rate: float = 0.02
    late_recording_rate: float = 0.01
    # non-business days (synthetic/approximate; Sat+Sun are always non-business)
    holidays: list[date] = Field(default_factory=lambda: [
        date(2025, 11, 9), date(2025, 12, 25), date(2026, 2, 5), date(2026, 3, 20), date(2026, 3, 21),
        date(2026, 3, 23), date(2026, 5, 1), date(2026, 5, 27), date(2026, 5, 28), date(2026, 6, 26),
        date(2026, 8, 14), date(2026, 11, 9), date(2024, 12, 25), date(2025, 2, 5), date(2025, 3, 23),
        date(2025, 3, 31), date(2025, 4, 1), date(2025, 5, 1), date(2025, 6, 6), date(2025, 6, 7),
        date(2025, 7, 6), date(2025, 8, 14), date(2024, 11, 9),
    ])

    @field_validator("profile")
    @classmethod
    def _profile(cls, v: str) -> str:
        if v not in (*PROFILES, "custom"):
            raise ValueError(f"profile must be one of {[*PROFILES, 'custom']}")
        return v

    @property
    def n_customers(self) -> int:
        if self.customers is not None:
            return self.customers
        if self.profile == "custom":
            raise ConfigError("custom profile requires --customers")
        return PROFILES[self.profile]

    @property
    def n_accounts(self) -> int:
        return max(self.n_customers, round(self.n_customers * self.accounts_per_customer))

    @property
    def run_id(self) -> str:
        return f"{self.profile}-n{self.n_customers}-seed{self.seed}-{self.as_of_date:%Y%m%d}"


def load_config(path: Path | None = None, **overrides) -> GenConfig:
    """Config precedence: defaults < TOML file < explicit (non-None) CLI overrides."""
    data: dict = {}
    if path:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return GenConfig(**data)
