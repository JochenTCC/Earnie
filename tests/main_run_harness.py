"""Shared monkeypatch harness for main.main() orchestration tests.

Seams match current main.py call sites. When main.py adds required I/O or
renames a stubbed entry point, update this module — not each test file.

Patched (non-exhaustive of all main imports, but enough for a silent/full run):
  config.reload_config / is_loxone_silent_mode / is_sunrise_planning_horizon /
  get_battery_params
  profile_manager (month check, planning window, matrix)
  loxone_client (flex kw, resolve live power, snapshot, consumers)
  ehal_live.read_ess_soc / read_live_power_kw
  awattar_client.fetch_awattar_prices
  data.live_market_prices.fetch_live_day_ahead_prices
  consumer_targets.resolve_consumer_daily_targets
  optimizer.prepare_optimization_matrix / get_consumer_remaining_kwh /
  milp_optimizer / battery_plan_kw_from_control / register_consumer_delivery /
  calculate_optimization_savings
  pv_tuner.get_pv_delta_and_update
  cons_data_store / optimization_history / collect_thermal_observability
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import main as main_module
from data.planning_window import PlanningWindow


def sample_planning_window() -> PlanningWindow:
    from data.planning_window import hourly_slots_inclusive

    tz = ZoneInfo("Europe/Vienna")
    start = datetime(2026, 6, 15, 10, 0, tzinfo=tz)
    sunset_1 = datetime(2026, 6, 15, 21, 0, tzinfo=tz)
    sunset_2 = datetime(2026, 6, 16, 21, 0, tzinfo=tz)
    sunrise = datetime(2026, 6, 16, 5, 30, tzinfo=tz)
    end = datetime(2026, 6, 17, 5, 30, tzinfo=tz)
    slots = hourly_slots_inclusive(start, end)
    return PlanningWindow(
        start=start,
        end=end,
        sunset_1=sunset_1,
        sunset_2=sunset_2,
        sunrise_anchor=sunrise,
        slot_datetimes=slots,
        timezone_name="Europe/Vienna",
        latitude=47.404,
        longitude=9.743,
    )


def _passthrough_prepare_matrix(matrix, targets, consumers=None):
    return matrix, {}, targets


def patch_main_run(monkeypatch, *, silent: bool = True) -> None:
    """Stub I/O and heavy seams so main.main() completes without network/MILP."""
    monkeypatch.setattr(main_module.config, "reload_config", lambda: None)
    monkeypatch.setattr(main_module.config, "is_loxone_silent_mode", lambda: silent)
    monkeypatch.setattr(main_module.config, "is_sunrise_planning_horizon", lambda: True)
    monkeypatch.setattr(
        main_module.profile_manager,
        "check_and_update_profile_if_new_month",
        lambda: None,
    )
    monkeypatch.setattr(
        main_module.profile_manager,
        "compute_live_planning_window",
        sample_planning_window,
    )
    monkeypatch.setattr(
        main_module.ehal_live,
        "read_ess_soc",
        lambda: 50.0,
    )
    monkeypatch.setattr(
        "data.live_market_prices.fetch_live_day_ahead_prices",
        lambda planning_end=None: [
            {"timestamp": datetime(2026, 6, 15, 10, 0), "price_buy": 10.0}
        ],
    )
    # main imports the symbol; patch the bound name on main_module too
    monkeypatch.setattr(
        main_module,
        "fetch_live_day_ahead_prices",
        lambda planning_end=None: [
            {"timestamp": datetime(2026, 6, 15, 10, 0), "price_buy": 10.0}
        ],
    )
    monkeypatch.setattr(
        main_module.profile_manager,
        "build_live_planning_matrix",
        lambda _market, _window: [
            {
                "expected_p_pv": 2.0,
                "expected_p_act": 1.0,
                "price_buy": 10.0,
                "k_act": 13.44,
                "hour": 10,
            }
        ],
    )
    monkeypatch.setattr(main_module.ehal_live, "read_live_power_kw", lambda: None)
    monkeypatch.setattr(
        main_module.consumer_targets,
        "resolve_consumer_daily_targets",
        lambda **_: {},
    )
    monkeypatch.setattr(
        main_module.optimizer,
        "prepare_optimization_matrix",
        _passthrough_prepare_matrix,
    )
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
        "fetch_flexible_consumers_live_kw",
        lambda **_: {},
    )
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
    monkeypatch.setattr(main_module.optimizer, "calculate_optimization_savings", lambda *a, **k: None)
