"""Tests for event vs regular main.py side effects (Nebenläufer-Schutz)."""
from __future__ import annotations

from unittest.mock import MagicMock

import main as main_module
from optimizer.event_trigger import TRIGGER_QUARTER_HOUR, build_run_trigger
from tests.main_run_harness import patch_main_run


def test_event_run_uses_peek_and_books_live_delivery(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
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
    monkeypatch.setattr(
        main_module,
        "fetch_trigger_snapshot",
        lambda _specs: {"eauto_plugged_in": True},
    )

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
    patch_main_run(monkeypatch, silent=True)
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

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    update.assert_called_once()
    peek.assert_not_called()
    register.assert_called_once()
    assert register.call_args.kwargs["book_planned"] is True
    cons_data.assert_called_once()
    assert saved[0]["run_trigger"] == TRIGGER_QUARTER_HOUR
    assert saved[0]["k_push_act"] == main_module.config.get_push_price_cent()


def test_run_payload_forecast_pv_kw_uses_pre_overlay_matrix(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    monkeypatch.setattr(
        main_module.profile_manager,
        "build_live_planning_matrix",
        lambda _market, _window: [
            {"expected_p_pv": 2.5, "expected_p_act": 1.0, "price_buy": 10.0, "hour": 10}
        ],
    )
    monkeypatch.setattr(
        main_module.ehal_live,
        "read_live_power_kw",
        lambda: {"house": 1.0, "pv": 4.2, "grid": 0.0, "battery": 0.0},
    )
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_peek", MagicMock(return_value=1.5))
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_and_update", MagicMock(return_value=2.0))
    saved: list[dict] = []
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert saved[0]["forecast_pv_kw"] == 2.5
    assert saved[0]["consumption_snapshot"]["pv_kw"] == 4.2


def test_regular_run_continues_when_pv_delta_unavailable(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    register = MagicMock()
    cons_data = MagicMock(return_value=0)
    saved: list[dict] = []

    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_peek", MagicMock(return_value=None))
    monkeypatch.setattr(main_module.pv_tuner, "get_pv_delta_and_update", MagicMock(return_value=None))
    monkeypatch.setattr(main_module.optimizer, "register_consumer_delivery", register)
    monkeypatch.setattr(main_module.cons_data_store, "record_and_maybe_flush", cons_data)
    monkeypatch.setattr(
        main_module.run_state,
        "save_run_state",
        lambda payload: saved.append(payload),
    )

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    register.assert_called_once()
    cons_data.assert_called_once()
    assert cons_data.call_args.kwargs["pv_kwh_interval"] == 0.0
    assert saved[0]["pv_delta_kwh"] == 0.0
