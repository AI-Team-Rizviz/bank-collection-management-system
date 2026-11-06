"""Business calendar, timezone helpers, deterministic RNG/ID derivation."""
from __future__ import annotations

import calendar
import hashlib
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    KARACHI = ZoneInfo("Asia/Karachi")
except Exception:  # tzdata missing: Karachi has been a fixed UTC+5 since 2009
    KARACHI = timezone(timedelta(hours=5), "Asia/Karachi")
UTC = timezone.utc


def local_dt(d: date, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm, ss), tzinfo=KARACHI)


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


def local_date(dt: datetime) -> date:
    return dt.astimezone(KARACHI).date()


def add_months(d: date, months: int, anchor_day: int | None = None) -> date:
    anchor = anchor_day or d.day
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    return date(y, m, min(anchor, calendar.monthrange(y, m)[1]))


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def month_ends_between(start_excl: date, end_incl: date) -> list[date]:
    out, cur = [], month_end(start_excl + timedelta(days=1)) if start_excl < end_incl else None
    while cur is not None and cur <= end_incl:
        out.append(cur)
        cur = month_end(cur + timedelta(days=1))
    return out


class Calendar:
    """Mon-Fri business days minus configured holidays."""

    def __init__(self, holidays=()):
        self.holidays = set(holidays)

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def next_business_day(self, d: date) -> date:
        while not self.is_business_day(d):
            d += timedelta(days=1)
        return d

    def add_business_days(self, d: date, n: int) -> date:
        while n > 0:
            d = self.next_business_day(d + timedelta(days=1))
            n -= 1
        return d


# --------------------------------------------------------------------------- determinism
def rng_for(seed: int, *key: object) -> random.Random:
    """Independent RNG per logical entity => output does not depend on chunking/iteration order."""
    digest = hashlib.sha256(("|".join(map(str, (seed, *key)))).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def run_namespace(run_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"bank-cms-seed/{run_id}")


def uid(ns: uuid.UUID, *key: object) -> uuid.UUID:
    return uuid.uuid5(ns, "|".join(map(str, key)))
