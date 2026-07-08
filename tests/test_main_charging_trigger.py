"""Tests für Event-Läufe in main.py (Nebenläufer-Schutz)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import main as main_module
from data.planning_window import PlanningWindow
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


def _patch_main_dependencies(monkeypatch):
    monkeypatch.setattr(main_module.config, "reload_config", lambda: None)
    monkeypatch.setattr(main_module.config, "is_loxone_silent_mode", lambda: True)
    monkeypatch.setattr(main_module.config, "is_sunset_planning_horizon", lambda: True)
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
        lambda *a, **k: (0, 0.0, 99.0, {"eauto": 3.5}, {"eauto": 0}, {}, {}),
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
        "build_sent_loxone_snapshot",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        main_module,
        "fetch_trigger_snapshot",
        lambda _specs: {"eauto_plugged_in": True},
    )


def test_event_run_uses_peek_and_books_live_delivery(monkeypatch):
    _patch_main_dependencies(monkeypatch)
    peek = MagicMock(return_value=1.5)
    update = MagicMock(return_value=1.5)
    register = MagicMock(return_value={})
    cons_data = MagicMock(return_value=0)
    saved: list[dict] = []

    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_peek", peek)
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_and_update", update)
    monkeypatch.setattr(main_module.optimizer, "register_consumer_delivery", register)
    monkeypatch.setattr(main_module.cons_data_store, "record_and_maybe_flush", cons_data)
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )
    monkeypatch.setattr(main_module.optimization_history, "append_production_run", lambda _p: None)

    run_trigger = build_run_trigger("eauto_plugged_in")
    main_module.main(run_trigger=run_trigger)

    peek.assert_called_once()
    update.assert_not_called()
    register.assert_called_once()
    assert register.call_args.kwargs["book_planned"] is False
    cons_data.assert_not_called()
    assert saved[0]["run_trigger"] == run_trigger
    assert saved[0]["event_trigger_snapshot"] == {"eauto_plugged_in": True}


def test_regular_run_uses_update_and_side_effects(monkeypatch):
    _patch_main_dependencies(monkeypatch)
    peek = MagicMock(return_value=1.5)
    update = MagicMock(return_value=2.0)
    register = MagicMock()
    cons_data = MagicMock(return_value=0)
    saved: list[dict] = []

    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_peek", peek)
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_and_update", update)
    monkeypatch.setattr(main_module.optimizer, "register_consumer_delivery", register)
    monkeypatch.setattr(main_module.cons_data_store, "record_and_maybe_flush", cons_data)
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )
    monkeypatch.setattr(main_module.optimization_history, "append_production_run", lambda _p: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    update.assert_called_once()
    peek.assert_not_called()
    register.assert_called_once()
    assert register.call_args.kwargs["book_planned"] is True
    cons_data.assert_called_once()
    assert saved[0]["run_trigger"] == TRIGGER_QUARTER_HOUR
    assert saved[0]["k_push_act"] == main_module.config.get_push_price_cent()


def test_run_payload_forecast_pv_kw_uses_pre_overlay_matrix(monkeypatch):
    _patch_main_dependencies(monkeypatch)
    monkeypatch.setattr(
        main_module.profile_manager,
        "build_live_planning_matrix",
        lambda _market, _window: [
            {"expected_p_pv": 2.5, "expected_p_act": 1.0, "price_buy": 10.0, "hour": 10}
        ],
    )
    monkeypatch.setattr(
        main_module.loxone_client,
        "fetch_loxone_live_power",
        lambda: {"house": 1.0, "pv": 4.2, "grid": 0.0, "battery": 0.0},
    )
    monkeypatch.setattr(
        main_module.loxone_client,
        "fetch_flexible_consumers_live_kw",
        lambda **_: {},
    )
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_peek", MagicMock(return_value=1.5))
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_and_update", MagicMock(return_value=2.0))
    monkeypatch.setattr(main_module.optimizer, "register_consumer_delivery", MagicMock())
    monkeypatch.setattr(main_module.cons_data_store, "record_and_maybe_flush", MagicMock(return_value=0))
    saved: list[dict] = []
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )
    monkeypatch.setattr(main_module.optimization_history, "append_production_run", lambda _p: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert saved[0]["forecast_pv_kw"] == 2.5
    assert saved[0]["consumption_snapshot"]["pv_kw"] == 4.2
