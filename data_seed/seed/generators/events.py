"""Turn the simulation's raw business events into `banking_events` + `event_delivery_status` rows.

Event timestamps preserve business time (occurred_at) separately from ingestion time (recorded_at)
and from simulated broker delivery time (event_delivery_status.delivered_at). Duplicate and delayed
(out-of-order) deliveries reuse the SAME event_id; they never create new financial postings.
Kafka publishing can later read `banking_events` (ordered by account_sequence / occurred_at) and
write to a topic without touching the generator.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from seed.simulation.timeline import local_dt, rng_for, uid

TYPE_ORDER = {t: i for i, t in enumerate([
    "ACCOUNT_CREATED", "LOAN_DISBURSED", "INSTALLMENT_DUE", "CARD_STATEMENT_GENERATED", "PAYMENT_ATTEMPT_FAILED",
    "PAYMENT_POSTED", "PAYMENT_REVERSED", "ACCOUNT_RESTRUCTURED", "REPAYMENT_SCHEDULE_CHANGED", "ACCOUNT_DELINQUENT",
    "DELINQUENCY_BUCKET_CHANGED", "DELINQUENCY_CURED", "RISK_PROFILE_UPDATED", "ACCOUNT_CLOSED"])}
SOURCE = {"INSTALLMENT": "MOCK_LMS", "CARD": "MOCK_CARD_SYSTEM"}


def jsonable(v):
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    return v


def build_event_rows(cfg, ns, sim, customer_id, extra_events=()) -> tuple[list[dict], list[dict]]:
    plan = sim.plan
    raw = list(sim.events) + list(extra_events)
    raw.sort(key=lambda e: (e.when, TYPE_ORDER[e.etype], e.key))
    rng = rng_for(cfg.seed, "events", plan.number)
    cap = local_dt(cfg.as_of_date, 23, 59, 59)
    system = SOURCE["CARD" if sim.is_card else "INSTALLMENT"]
    events, deliveries = [], []
    for seq, e in enumerate(raw, start=1):
        eid = f"EVT-{uid(ns, 'event', plan.number, e.etype, e.key)}"
        rec = e.when + timedelta(seconds=rng.randint(1, 5))
        if e.back_valued:
            rec += timedelta(hours=rng.randint(24, 72))
        elif rng.random() < cfg.late_recording_rate:
            rec += timedelta(hours=rng.randint(2, 48))          # late-arriving event
        rec = max(e.when, min(rec, cap))
        src = {"ACCOUNT_CREATED": "MOCK_CORE_BANKING", "RISK_PROFILE_UPDATED": "MOCK_RISK_ENGINE"}.get(e.etype, system)
        events.append(dict(event_id=eid, event_type=e.etype, source_system=src, account_id=sim.account_id,
                           account_number=plan.number, customer_id=customer_id, occurred_at=e.when, recorded_at=rec,
                           schema_version=1, account_sequence=seq, payload=jsonable(e.payload)))
        d1 = rec + timedelta(milliseconds=rng.randint(50, 2000))
        status = "DELIVERED"
        if rng.random() < cfg.delayed_delivery_rate:
            d1 += timedelta(hours=rng.randint(1, 72))             # out-of-order relative to business time
            status = "DELAYED"
        d1 = min(d1, cap + timedelta(days=3))
        deliveries.append(dict(delivery_id=uid(ns, "delivery", eid, 1), event_id=eid, attempt_no=1, delivered_at=d1,
                               delivery_status=status, is_duplicate=False))
        if rng.random() < cfg.duplicate_delivery_rate:
            deliveries.append(dict(delivery_id=uid(ns, "delivery", eid, 2), event_id=eid, attempt_no=2,
                                   delivered_at=d1 + timedelta(seconds=rng.randint(1, 600)),
                                   delivery_status="DUPLICATE", is_duplicate=True))
    return events, deliveries


def event_envelope(row: dict) -> dict:
    """The documented event contract (what a Kafka producer would publish)."""
    return {
        "event_id": row["event_id"], "event_type": row["event_type"], "source_system": row["source_system"],
        "account_id": row["account_number"], "occurred_at": _iso(row["occurred_at"]),
        "recorded_at": _iso(row["recorded_at"]), "schema_version": row["schema_version"],
        "payload": row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"]),
    }


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v
