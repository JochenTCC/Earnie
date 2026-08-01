"""Tests for loxone_writes / debug snapshot persistence in main.py run_state."""
from __future__ import annotations

from unittest.mock import MagicMock

import main as main_module
from integrations.loxone_comm_trace import LoxoneWriteRecord
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
from tests.main_run_harness import patch_main_run


def _sample_savings_info():
    return {
        "baseline_cost_euro": 10.0,
        "optimized_cost_euro": 8.0,
        "savings_euro": 2.0,
        "matched_baseline_cost_euro": 9.0,
        "savings_matched_euro": 1.0,
        "baseline_consumption_kwh": 5.0,
        "matched_baseline_consumption_kwh": 4.5,
        "optimized_consumption_kwh": 4.0,
        "baseload_kwh": 1.0,
        "optimized_rows": [{"hour": 10, "Netzbezug (kWh)": 1.0}],
        "baseline_rows": [{"hour": 10}],
        "matched_baseline_rows": [],
        "applied_targets": [],
        "energy_comparison": [],
    }


def test_main_persists_live_optimization_debug_snapshot(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    monkeypatch.setattr(
        main_module.optimizer,
        "calculate_optimization_savings",
        lambda *a, **k: _sample_savings_info(),
    )
    monkeypatch.setattr(
        main_module.optimizer,
        "build_savings_snapshot",
        lambda info: {"savings_matched_euro": 1.0},
    )
    monkeypatch.setattr(main_module.optimizer, "overlay_main_run_on_rows", lambda rows, _state: rows)
    saved_debug: list[dict] = []
    monkeypatch.setattr(
        main_module.live_optimization_debug,
        "save_debug_snapshot",
        lambda payload, **_: saved_debug.append(payload),
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert saved_debug
    payload = saved_debug[0]
    assert payload["source"] == "main.py"
    assert payload["sync_reason"] == "main_synced"
    assert payload.get("planning_matrix")
    assert payload.get("planning_window")
    assert payload.get("simulation_rows")


def test_main_run_state_includes_loxone_writes_when_not_silent(monkeypatch):
    patch_main_run(monkeypatch, silent=False)
    saved: list[dict] = []
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )
    huawei = [LoxoneWriteRecord("SoC", 80.0, True, "2026-07-14T10:00:00")]
    flex = [LoxoneWriteRecord("Ernie_WP", 1.0, True, "2026-07-14T10:00:01")]
    monkeypatch.setattr(main_module.loxone_client, "send_huawei_modbus_states", lambda *a, **k: huawei)
    monkeypatch.setattr(main_module.loxone_client, "send_flexible_consumer_states", lambda *a, **k: flex)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert saved
    payload = saved[0]
    assert payload["loxone_writes"] == [
        {"io_name": "SoC", "value": 80.0, "success": True, "written_at": "2026-07-14T10:00:00"},
        {"io_name": "Ernie_WP", "value": 1.0, "success": True, "written_at": "2026-07-14T10:00:01"},
    ]
    assert payload["loxone_sent"] == {"Ernie_Mode": 1.0}


def test_main_run_state_omits_loxone_writes_when_silent(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    saved: list[dict] = []
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )
    send_huawei = MagicMock()
    send_flex = MagicMock()
    monkeypatch.setattr(main_module.loxone_client, "send_huawei_modbus_states", send_huawei)
    monkeypatch.setattr(main_module.loxone_client, "send_flexible_consumer_states", send_flex)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    send_huawei.assert_not_called()
    send_flex.assert_not_called()
    assert saved
    assert saved[0]["loxone_writes"] is None
