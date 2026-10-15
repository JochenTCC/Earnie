"""Regression R0: offline MILP replay from cycle-recorder entries."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

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
    token = cycle_recorder.begin_cycle(
        optimization_matrix=_sample_matrix(8, base=now.replace(minute=0, second=0)),
        planning_window={
            "start": now.isoformat(timespec="seconds"),
            "end": (now + timedelta(hours=24)).isoformat(timespec="seconds"),
            "horizon_hours": 24,
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
