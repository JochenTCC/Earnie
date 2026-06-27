"""Regressionstests gegen archivierte Produktiv-Dumps."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from optimizer import charging_context as cc
from optimizer import charging_session as cs
from tests.fixtures import prod_dump_fixtures as pdf

CASE_EAUTO = "eauto_deadline_missed_2026-06-27"


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value)[:19])


def _integrate_kw(rows: list[dict], start: datetime, end: datetime, key: str) -> float:
    total = 0.0
    for row in rows:
        ts = _parse_ts(row["written_at"])
        if not (start <= ts <= end):
            continue
        kw = float((row.get(key) or {}).get("eauto", 0) or 0)
        total += kw * 0.25
    return round(total, 2)


@pytest.fixture(scope="module")
def eauto_manifest() -> dict:
    return pdf.load_manifest(CASE_EAUTO)


@pytest.fixture(scope="module")
def eauto_history() -> list[dict]:
    return pdf.load_jsonl(CASE_EAUTO)


def test_prod_dump_archives_are_discoverable():
    assert CASE_EAUTO in pdf.list_prod_dump_ids()


def test_prod_dump_documents_observed_failure(eauto_manifest, eauto_history):
    reg = eauto_manifest["regression"]
    start = _parse_ts(reg["session_start"])
    end = _parse_ts(reg["deadline"])
    live_kwh = _integrate_kw(eauto_history, start, end, "flex_live_kw")
    assert live_kwh < float(reg["target_kwh"])
    assert live_kwh <= float(reg["observed_live_kwh_max"]) + 0.5


def test_prod_dump_schedule_indices_cross_midnight(eauto_manifest):
    reg = eauto_manifest["regression"]
    start = _parse_ts(reg["session_start"])
    deadline = _parse_ts(reg["deadline"])
    matrix = [
        {
            "slot_datetime": start + timedelta(hours=i),
            "hour": (start + timedelta(hours=i)).hour,
            "date": (start + timedelta(hours=i)).date(),
        }
        for i in range(24)
    ]
    consumer = {
        "id": "eauto",
        "charging_schedule": {"enabled": True},
    }
    ctx = {
        "active": True,
        "deadline": deadline,
        "use_time_window": False,
    }
    indices = cc.schedule_indices_for_consumer(matrix, 24, [0, 1], consumer, ctx)
    assert len(indices) >= int(reg["min_schedule_indices_from_22h"])


def test_prod_dump_session_state_survives_midnight(eauto_manifest):
    reg = eauto_manifest["regression"]
    state_path = pdf.fixture_file(CASE_EAUTO, "flexible_consumers_state.json")
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    consumer = {
        "id": "eauto",
        "charging_schedule": {"enabled": True},
    }
    contexts = {
        "eauto": {
            "active": True,
            "deadline": _parse_ts(reg["deadline"]),
            "target_kwh": float(reg["target_kwh"]),
        }
    }
    prior = {
        "date": "2026-06-26",
        "delivered": {"swimspa": 1.0},
        "charging_sessions": {
            "eauto": {
                "target_kwh": float(reg["target_kwh"]),
                "delivered_kwh": 2.0,
                "deadline": reg["deadline"],
            }
        },
    }
    normalized = cs.normalize_consumer_state(
        prior,
        "2026-06-27",
        contexts,
        {"eauto": consumer},
        now=_parse_ts("2026-06-27T05:00:00"),
    )
    assert normalized["delivered"] == {}
    assert normalized["charging_sessions"]["eauto"]["delivered_kwh"] == 2.0


def test_prod_dump_urgent_window_covers_remaining_before_deadline(eauto_manifest):
    reg = eauto_manifest["regression"]
    start = _parse_ts("2026-06-27T05:00:00")
    deadline = _parse_ts(reg["deadline"])
    remaining = float(reg["target_kwh"])
    matrix = [
        {
            "slot_datetime": start + timedelta(hours=i),
            "hour": (start + timedelta(hours=i)).hour,
            "date": (start + timedelta(hours=i)).date(),
        }
        for i in range(6)
    ]
    eligible = list(range(len(matrix)))
    urgent = cc.urgent_charging_indices(matrix, eligible, deadline, remaining, 3.68)
    assert urgent
    urgent_energy_h = len(urgent)
    assert urgent_energy_h * 3.68 >= remaining * 0.95
