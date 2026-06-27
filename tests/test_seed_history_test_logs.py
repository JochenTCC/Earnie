"""Tests für scripts/seed_history_test_logs.py"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts.seed_history_test_logs import seed_history_logs


def _sample_entries() -> list[dict]:
    return [
        {
            "written_at": "2026-06-24T10:00:00",
            "soc_percent": 50.0 + index,
            "mode": 0,
            "target_power_kw": 0.0,
            "market_price_cent": 10.0,
            "forecast_pv_kw": 2.0,
            "forecast_consumption_kw": 1.0,
            "battery_plan_kw": 0.5,
            "consumer_powers_kw": {},
            "consumption_snapshot": {
                "baseload_kw": 1.0,
                "pv_kw": 2.0,
                "flex_kw": {},
            },
        }
        for index in range(4)
    ]


def test_seed_history_logs_remaps_to_quarter_hour_slots(tmp_path):
    source = tmp_path / "source.jsonl"
    target = tmp_path / "runtime" / "optimization_history.jsonl"
    with open(source, "w", encoding="utf-8") as handle:
        for entry in _sample_entries():
            handle.write(json.dumps(entry) + "\n")

    anchor = datetime(2026, 6, 27, 12, 0, 0)
    summary = seed_history_logs(source, target, anchor=anchor)

    assert summary["entries"] == 4
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["completed_at"] == "2026-06-27T11:45:00"
    assert rows[0]["completed_at"] == "2026-06-27T11:00:00"
    assert all(row["source"] == "seed_history_test_logs.py" for row in rows)


def test_seed_history_logs_requires_nonempty_source(tmp_path):
    source = tmp_path / "empty.jsonl"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="keine Einträge"):
        seed_history_logs(source, tmp_path / "out.jsonl")
