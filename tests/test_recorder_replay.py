"""Regression R0: offline MILP replay from cycle-recorder entries."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import config
from runtime_store import cycle_recorder
from runtime_store.recorder_replay import replay_recorded_cycle
from tests.config_fixtures import (
    default_live_settings,
    house_battery_stub,
    main_hybrid_inverter,
    minimal_components_payload,
    minimal_config_payload,
    write_minimal_config_tree,
)


_TEST_BATTERY = {
    "id": "home",
    "battery_capacity_kwh": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_power_kw": 2.5,
    "max_charge_power_kw": 2.5,
    "max_discharge_power_kw": 2.5,
    "efficiency": 0.97,
    "control": "full",
}


def _cfg_with_battery(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(extra={"flexible_consumers": []}),
        components_payload=minimal_components_payload(
            extra={
                "inverters": [main_hybrid_inverter()],
                "batteries": [house_battery_stub()],
                "pv_systems": [],
            }
        ),
        live_settings={**default_live_settings(), "battery_ids": ["home"]},
    )
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(json.dumps({"silent_mode": False}), encoding="utf-8")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", config_path)
    monkeypatch.setenv("EARNIE_BACKTESTING_SCENARIOS_PATH", scenarios_path)
    monkeypatch.setenv("EARNIE_LOCAL_SETTINGS_PATH", str(local_path))
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(tmp_path / "config" / "components.json"))
    config.reinit_config()
    monkeypatch.setattr(config, "get_push_price_cent", lambda: 4.0)
    monkeypatch.setattr(config, "get_threshold_power", lambda: 0.05)
    monkeypatch.setattr(config, "get_battery_params", lambda: dict(_TEST_BATTERY))
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [dict(_TEST_BATTERY)])
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=True: [])
    cycle_recorder.reset_for_tests()


def _sample_matrix(n: int = 8, *, base: datetime | None = None) -> list[dict]:
    start = base or datetime.now().replace(minute=0, second=0, microsecond=0)
    rows: list[dict] = []
    for index in range(n):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "slot_datetime": slot,
                "hour": slot.hour,
                "date": slot.date(),
                "expected_p_pv": 1.5 + index * 0.1,
                "expected_p_act": 0.8,
                "k_act": 12.0 + index,
                "k_push_act": 4.0,
                "price_buy": 10.0,
            }
        )
    return rows


def test_replay_strict_stable_plan_hash(tmp_path, monkeypatch):
    _cfg_with_battery(tmp_path, monkeypatch)
    # Use "today" so prune_old_segments does not delete the fresh segment.
    now = datetime.now().replace(microsecond=0)
    matrix = _sample_matrix(8, base=now.replace(minute=0, second=0, microsecond=0))
    slot_times = [row["slot_datetime"].isoformat() for row in matrix]
    token = cycle_recorder.begin_cycle(
        optimization_matrix=matrix,
        planning_window={
            "start": now.isoformat(timespec="seconds"),
            "end": (now + timedelta(hours=24)).isoformat(timespec="seconds"),
            "horizon_hours": 24,
            "sunrise_anchor": slot_times[-1],
            "slot_datetimes": slot_times,
        },
        soc_percent=55.0,
        soc_percent_by_ess={"home": 55.0},
        targets={},
        timestamp=now,
    )
    assert token is not None
    assert cycle_recorder.finish_cycle(
        token,
        mode=0,
        target_power_kw=0.0,
        battery_plan_kw=0.0,
        consumer_powers_kw={},
    )
    segment = cycle_recorder.segment_path_for_day(now.date())
    entry = cycle_recorder.read_segment_cycles(segment)[0]
    # No thermal consumer reads the forecast, so the empty marker must not
    # break the replay.
    assert entry["start_state"]["outdoor_forecast"] is None
    recorder_root = cycle_recorder.recorder_dir()

    first = replay_recorded_cycle(
        entry,
        recorder_root=recorder_root,
        solver_mode="strict",
        verbose=False,
    )
    second = replay_recorded_cycle(
        entry,
        recorder_root=recorder_root,
        solver_mode="strict",
        verbose=False,
    )
    assert first.status == "Optimal"
    assert second.status == "Optimal"
    assert first.plan_hash == second.plan_hash
    assert first.cost_euro is not None
    assert second.cost_euro == pytest.approx(first.cost_euro, rel=1e-9)
    assert first.stage == "strict_only"
    assert first.n_slots == 8


class _StopAfterPrepare(Exception):
    pass


def _replay_reading_outdoor_forecast(monkeypatch, start_state: dict):
    """Run _solve_prepared_entry up to input prep, reading the forecast like a thermal consumer.

    Returns the series read and the mock that stands in for the live fetch.
    """
    from data import outdoor_forecast as of
    from runtime_store import recorder_replay

    read: list[tuple[list[float], str]] = []

    def _prepare(entry, cfg):
        read.append(of.get_outdoor_forecast_with_fallback(horizon=2, fallback_ambient_c=9.0))
        raise _StopAfterPrepare

    monkeypatch.setattr(recorder_replay, "_prepare_replay_inputs", _prepare)
    entry = {"timestamp": "2026-10-28T09:44:52", "start_state": start_state}
    with patch.object(of, "get_hourly_outdoor_forecast_c", return_value=[3.0, 4.0]) as fetch:
        with pytest.raises(_StopAfterPrepare):
            recorder_replay._solve_prepared_entry(entry, solver_mode="strict", verbose=False)
    return read, fetch


def test_replay_fails_loud_when_recorded_forecast_is_empty(tmp_path, monkeypatch):
    _cfg_with_battery(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="outdoor_forecast"):
        _replay_reading_outdoor_forecast(monkeypatch, {"outdoor_forecast": None})


def test_replay_fetches_live_forecast_for_cycles_without_the_key(tmp_path, monkeypatch):
    _cfg_with_battery(tmp_path, monkeypatch)
    read, fetch = _replay_reading_outdoor_forecast(monkeypatch, {})
    fetch.assert_called_once()
    assert read == [([3.0, 4.0], "open_meteo")]


def test_replay_serves_recorded_forecast(tmp_path, monkeypatch):
    _cfg_with_battery(tmp_path, monkeypatch)
    recorded = {"values_c": [1.5, 2.5, 3.5], "source": "open_meteo"}
    read, fetch = _replay_reading_outdoor_forecast(monkeypatch, {"outdoor_forecast": recorded})
    fetch.assert_not_called()
    assert read == [([1.5, 2.5], "open_meteo")]


def _bind_limit_soc_marker(monkeypatch, marker: str = "ev.e_auto.get_evcs_limit_soc"):
    from settings import ehal_marker_resolve

    consumer = {"id": "e_auto"}
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=True: [consumer])
    monkeypatch.setattr(ehal_marker_resolve, "marker_get_evcs_limit_soc", lambda c: marker)
    return consumer, marker


def test_replay_serves_recorded_ev_limit_soc(tmp_path, monkeypatch):
    from integrations import ehal_live
    from runtime_store.recorder_replay import _recorded_ev_limit_soc
    from settings.ehal_marker_resolve import resolve_get_evcs_limit_soc

    consumer, marker = _bind_limit_soc_marker(monkeypatch)
    monkeypatch.setattr(ehal_live, "read_generic_value", lambda address: None)
    entry = {"start_state": {"ev_limit_soc_percent": {"e_auto": 80.0}}}
    with _recorded_ev_limit_soc(entry, config):
        assert resolve_get_evcs_limit_soc(consumer) == 80.0
    with pytest.raises(ValueError, match="nicht lesbar"):
        resolve_get_evcs_limit_soc(consumer)


def test_replay_fails_loud_without_recorded_ev_limit_soc(monkeypatch):
    from runtime_store.recorder_replay import _recorded_ev_limit_soc
    from settings.ehal_marker_resolve import resolve_get_evcs_limit_soc

    consumer, _marker = _bind_limit_soc_marker(monkeypatch)
    with _recorded_ev_limit_soc({"start_state": {}}, config):
        # Entering is fine: cycles that never read the marker still replay.
        with pytest.raises(ValueError, match="ev_limit_soc_percent"):
            resolve_get_evcs_limit_soc(consumer)


def test_recorder_collects_ev_limit_soc(monkeypatch):
    from integrations import ehal_live

    _bind_limit_soc_marker(monkeypatch)
    monkeypatch.setattr(ehal_live, "read_generic_value", lambda address: 75.0)
    assert cycle_recorder._collect_ev_limit_soc() == {"e_auto": 75.0}


_THERMAL_READINGS = {
    "actual_c": 36.5,
    "setpoint_c": 38.0,
    "ambient_c": 7.0,
    "tolerance_c": None,
    "heating_active": False,
    "missing_signals": ["get_temperature_tolerance_c"],
}


def test_replay_serves_recorded_thermal_readings():
    from integrations import ehal_live
    from runtime_store.recorder_replay import _recorded_thermal_readings

    original = ehal_live.fetch_thermal_readings
    entry = {"start_state": {"thermal_readings": {"pool": _THERMAL_READINGS}}}
    with _recorded_thermal_readings(entry):
        assert ehal_live.fetch_thermal_readings({"id": "pool"}) == _THERMAL_READINGS
        with pytest.raises(ValueError, match="thermal_readings"):
            ehal_live.fetch_thermal_readings({"id": "other"})
    assert ehal_live.fetch_thermal_readings is original


def test_recorder_collects_thermal_readings_for_enabled_thermal_control(monkeypatch):
    from integrations import ehal_live

    consumers = [
        {"id": "pool", "thermal_control": {"enabled": True}},
        {"id": "boiler", "thermal_control": {"enabled": False}},
        {"id": "dishwasher"},
    ]
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=True: consumers)
    fetched: list[str] = []

    def _fetch(consumer, **_kwargs):
        fetched.append(consumer["id"])
        return dict(_THERMAL_READINGS)

    monkeypatch.setattr(ehal_live, "fetch_thermal_readings", _fetch)
    assert cycle_recorder._collect_thermal_readings() == {"pool": _THERMAL_READINGS}
    assert fetched == ["pool"]


def test_sunrise_index_none_without_recorded_anchor():
    from runtime_store.recorder_replay import _recorded_sunrise_soc_min_index

    entry = {
        "planning_window": {
            "slot_datetimes": ["2026-10-28T10:00:00+01:00", "2026-10-28T10:15:00+01:00"],
            "seed_anchor": "2026-10-28T10:00:00+01:00",
        }
    }
    assert _recorded_sunrise_soc_min_index(entry) is None


def test_sunrise_index_from_recorded_window():
    from runtime_store.recorder_replay import _recorded_sunrise_soc_min_index

    entry = {
        "planning_window": {
            "sunrise_anchor": "2026-10-29T07:03:11+01:00",
            "slot_datetimes": [
                "2026-10-28T10:00:00+01:00",
                "2026-10-29T07:00:00+01:00",
                "2026-10-29T07:15:00+01:00",
            ],
        }
    }
    assert _recorded_sunrise_soc_min_index(entry) == 1


def test_sunrise_index_fails_loud_without_slots():
    from runtime_store.recorder_replay import _recorded_sunrise_soc_min_index

    with pytest.raises(ValueError, match="slot_datetimes"):
        _recorded_sunrise_soc_min_index(
            {"planning_window": {"sunrise_anchor": "2026-10-29T07:00:00+01:00"}}
        )


def test_restored_matrix_keeps_recorded_utc_offset():
    from runtime_store.recorder_replay import _coerce_matrix_datetimes

    rows = _coerce_matrix_datetimes(
        [{"slot_datetime": "2026-10-28T00:15:00+01:00"}, {"slot_datetime": "2026-10-28T00:30:00"}]
    )
    assert rows[0]["slot_datetime"].utcoffset() == timedelta(hours=1)
    assert rows[0]["hour"] == 0
    assert rows[1]["slot_datetime"].tzinfo is None


def test_recorded_reserves_shape_battery_params(monkeypatch):
    from optimizer import powerstation_live
    from runtime_store import recorder_replay as rr

    seen = {}

    def _apply(params, reserves=None):
        seen["reserves"] = reserves
        return {**params, "_virtual_reserve_asap_kwh": 0.38}

    monkeypatch.setattr(powerstation_live, "apply_reserves_to_battery_params", _apply)
    reserves = [{"powerstation_id": "virtual_gs", "asap_charge_kwh": 0.38}]
    out = rr._battery_params_with_recorded_reserves(
        {"capacity_kwh": 15.0}, {"active_reserves": reserves}
    )
    assert seen["reserves"] == reserves
    assert out["_virtual_reserve_asap_kwh"] == 0.38


def test_cycles_without_recorded_reserves_keep_config_params():
    from runtime_store import recorder_replay as rr

    params = {"capacity_kwh": 15.0}
    assert rr._battery_params_with_recorded_reserves(params, {}) is params


def test_recorded_reserves_must_be_a_list():
    from runtime_store import recorder_replay as rr

    with pytest.raises(TypeError, match="active_reserves"):
        rr._battery_params_with_recorded_reserves({}, {"active_reserves": {}})
