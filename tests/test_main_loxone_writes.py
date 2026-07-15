"""Tests für loxone_writes in main.py run_state."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import main as main_module
from data.planning_window import PlanningWindow
from integrations.loxone_comm_trace import LoxoneWriteRecord
from optimizer.event_trigger import TRIGGER_QUARTER_HOUR, build_run_trigger


def _sample_planning_window() -> PlanningWindow:
    tz = ZoneInfo("Europe/Vienna")
    start = datetime(2026, 6, 15, 10, 0, tzinfo=tz)
    sunset_1 = datetime(2026, 6, 15, 21, 0, tzinfo=tz)
    sunset_2 = datetime(2026, 6, 16, 21, 0, tzinfo=tz)
    sunrise = datetime(2026, 6, 16, 5, 30, tzinfo=tz)
    slots = tuple(start + __import__("datetime").timedelta(hours=i) for i in range(35))
    return PlanningWindow(
        start=start,
        end=sunset_2,
        sunset_1=sunset_1,
        sunset_2=sunset_2,
        sunrise_anchor=sunrise,
        slot_datetimes=slots,
        timezone_name="Europe/Vienna",
        latitude=47.404,
        longitude=9.743,
    )


def _patch_main_core(monkeypatch, *, silent: bool):
    monkeypatch.setattr(main_module.config, "reload_config", lambda: None)
    monkeypatch.setattr(main_module.config, "is_loxone_silent_mode", lambda: silent)
    monkeypatch.setattr(main_module.config, "is_sunrise_planning_horizon", lambda: True)
    monkeypatch.setattr(main_module.config, "get_event_triggers", lambda: [])
    monkeypatch.setattr(
        main_module.profile_manager,
        "check_and_update_profile_if_new_month",
        lambda: None,
    )
    monkeypatch.setattr(
        main_module.profile_manager,
        "compute_live_planning_window",
        _sample_planning_window,
    )
    monkeypatch.setattr(
        main_module.loxone_client,
        "fetch_loxone_generic_value",
        lambda _name: 50.0,
    )
    monkeypatch.setattr(
        main_module.awattar_client,
        "fetch_awattar_prices",
        lambda planning_end=None: [{"timestamp": datetime(2026, 6, 15, 10, 0), "price_buy": 10.0}],
    )
    monkeypatch.setattr(
        main_module.profile_manager,
        "build_live_planning_matrix",
        lambda _market, _window: [{"expected_p_pv": 2.0, "expected_p_act": 1.0, "price_buy": 10.0, "hour": 10}],
    )
    monkeypatch.setattr(main_module.loxone_client, "fetch_loxone_live_power", lambda: None)
    monkeypatch.setattr(
        main_module.consumer_targets,
        "resolve_consumer_daily_targets",
        lambda **_: {},
    )
    monkeypatch.setattr(main_module.optimizer, "resolve_charging_contexts", lambda *a, **k: {})
    monkeypatch.setattr(main_module.optimizer, "get_consumer_remaining_kwh", lambda **_: {})
    monkeypatch.setattr(main_module.loxone_client, "consumers_with_live_nominal_power", lambda: [])
    monkeypatch.setattr(
        main_module.optimizer,
        "milp_optimizer",
        lambda *a, **k: (0, 0.0, 99.0, {}, {}, {}, {}),
    )
    monkeypatch.setattr(main_module.config, "get_battery_params", lambda: {"max_power_kw": 2.5})
    monkeypatch.setattr(main_module.optimizer, "battery_plan_kw_from_control", lambda *a, **k: 0.0)
    monkeypatch.setattr(
        main_module.loxone_client,
        "resolve_flexible_consumers_live_power",
        lambda **_: MagicMock(kw={}, chart_kw={}, measured_ids=frozenset()),
    )
    monkeypatch.setattr(
        main_module.loxone_client,
        "build_sent_loxone_snapshot",
        lambda *a, **k: {"Ernie_Mode": 1.0},
    )
    monkeypatch.setattr(main_module.optimizer, "register_consumer_delivery", lambda *a, **k: {})
    monkeypatch.setattr(main_module.cons_data_store, "record_and_maybe_flush", lambda *a, **k: 0)
    monkeypatch.setattr(main_module.optimization_history, "append_production_run", lambda _p: None)
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_and_update", lambda: 0.0)
    monkeypatch.setattr(main_module, "collect_thermal_observability", lambda *a, **k: [])
    monkeypatch.setattr(
        main_module,
        "fetch_trigger_snapshot",
        lambda _specs: {},
    )
    monkeypatch.setattr(main_module.optimizer, "calculate_optimization_savings", lambda *a, **k: None)


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
    _patch_main_core(monkeypatch, silent=True)
    monkeypatch.setattr(
        main_module.optimizer,
        "calculate_optimization_savings",
        lambda *a, **k: _sample_savings_info(),
    )
    monkeypatch.setattr(main_module.optimizer, "build_savings_snapshot", lambda info: {"savings_matched_euro": 1.0})
    monkeypatch.setattr(main_module.optimizer, "overlay_main_run_on_rows", lambda rows, _state: rows)
    saved_debug: list[dict] = []
    monkeypatch.setattr(
        main_module.live_optimization_debug,
        "save_debug_snapshot",
        lambda payload, **_: saved_debug.append(payload),
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)

    main_module.main(run_trigger=build_run_trigger(TRIGGER_QUARTER_HOUR))

    assert saved_debug
    payload = saved_debug[0]
    assert payload["source"] == "main.py"
    assert payload["sync_reason"] == "main_synced"
    assert payload.get("planning_matrix")
    assert payload.get("planning_window")
    assert payload.get("simulation_rows")


def test_main_run_state_includes_loxone_writes_when_not_silent(monkeypatch):
    _patch_main_core(monkeypatch, silent=False)
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

    main_module.main(run_trigger=build_run_trigger(TRIGGER_QUARTER_HOUR))

    assert saved
    payload = saved[0]
    assert payload["loxone_writes"] == [
        {"io_name": "SoC", "value": 80.0, "success": True, "written_at": "2026-07-14T10:00:00"},
        {"io_name": "Ernie_WP", "value": 1.0, "success": True, "written_at": "2026-07-14T10:00:01"},
    ]
    assert payload["loxone_sent"] == {"Ernie_Mode": 1.0}


def test_main_run_state_omits_loxone_writes_when_silent(monkeypatch):
    _patch_main_core(monkeypatch, silent=True)
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

    main_module.main(run_trigger=build_run_trigger(TRIGGER_QUARTER_HOUR))

    send_huawei.assert_not_called()
    send_flex.assert_not_called()
    assert saved
    assert saved[0]["loxone_writes"] is None
