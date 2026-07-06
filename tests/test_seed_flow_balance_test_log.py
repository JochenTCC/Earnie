"""Tests für scripts/seed_flow_balance_test_log.py."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from runtime_store.history_timeline import entry_to_chart_row
from scripts.flow_balance_test_data import (
    flow_balance_flex_pairs,
    flow_balance_scenario_rows,
)
from scripts.seed_flow_balance_test_log import seed_flow_balance_test_log
from ui.chart_flow_balance import build_flow_balance_segments

_TZ = ZoneInfo("Europe/Vienna")


def test_seed_flow_balance_test_log_writes_nine_scenarios(tmp_path):
    target = tmp_path / "runtime" / "optimization_history.jsonl"
    anchor = datetime(2026, 7, 6, 14, 0, 0, tzinfo=_TZ)
    summary = seed_flow_balance_test_log(target, anchor=anchor)

    assert summary["entries"] == 9
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["scenario"] == "flow_balance_A"
    assert rows[-1]["scenario"] == "flow_balance_I"
    assert rows[-1]["completed_at"].startswith("2026-07-06T13:45:00")

    flex = flow_balance_flex_pairs()
    meta = {item.scenario_id: item for item in flow_balance_scenario_rows()}
    for entry in rows:
        scenario_id = entry["scenario"].replace("flow_balance_", "")
        chart_row = entry_to_chart_row(
            entry,
            datetime.fromisoformat(entry["completed_at"]),
        )
        slot = build_flow_balance_segments(chart_row, flex_consumers=flex)
        assert slot.offset_kw == meta[scenario_id].offset_kw
