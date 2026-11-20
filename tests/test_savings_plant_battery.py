"""Baselines and the ledger's shadow plant run the plant battery (savings_v 3, spec § 3).

With several house batteries both sides of the saving are the same plant: summed capacity
and power, energy-weighted SoC. With one house battery every path is unchanged, so the
ledger and the saving of such a house stay the same to the cent.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import config
from optimizer import sim_costs
from optimizer.milp_horizon import plant_battery_params
from optimizer.sim_baseline import _baseline_battery_params
from runtime_store import power_interval_sampler as sampler
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store

TZ = ZoneInfo("Europe/Vienna")


def _battery(ess_id: str, capacity: float, **overrides) -> dict:
    battery = {
        "id": ess_id,
        "battery_capacity_kwh": capacity,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
        "standby_power_kw": 0.02,
        "control": "full",
    }
    battery.update(overrides)
    return battery


SMALL = _battery("a", 5.0)
LARGE = _battery("b", 15.0, efficiency=0.9)
TWO = [SMALL, LARGE]


def _closed(**soc: object) -> dict:
    return {
        "interval_start": "2026-11-18T12:00:00",
        "sample_count": 15,
        "pv_kw": 1.0,
        "grid_kw": 0.2,
        "battery_kw": 0.0,
        "house_kw": 1.2,
        **soc,
    }


# --- battery of the baselines and the shadow plant -------------------------------------------


def test_several_batteries_baseline_and_shadow_run_the_plant_battery() -> None:
    plant = plant_battery_params(TWO)
    assert _baseline_battery_params(TWO) == plant
    assert sl.shadow_battery_params(TWO) == plant
    assert plant["battery_capacity_kwh"] == pytest.approx(20.0)
    assert plant["max_discharge_power_kw"] == pytest.approx(10.0)


def test_baseline_without_params_reads_the_plant_of_the_live_config(monkeypatch) -> None:
    monkeypatch.setattr(config, "get_battery_params_list", lambda: list(TWO))
    assert _baseline_battery_params(None) == plant_battery_params(TWO)


def test_one_battery_is_taken_as_is(monkeypatch) -> None:
    assert _baseline_battery_params([SMALL]) == SMALL
    assert sl.shadow_battery_params([SMALL]) == SMALL
    single = {"battery_capacity_kwh": 7.0, "efficiency": 0.9}
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [dict(SMALL)])
    monkeypatch.setattr(config, "get_battery_params", lambda: single)
    assert _baseline_battery_params(None) is single


# --- plant SoC of a closed slot --------------------------------------------------------------


def test_one_battery_keeps_the_logged_soc() -> None:
    closed = _closed(soc_start_percent=40.0, soc_end_percent=41.0)
    assert sl.with_plant_soc(closed, [SMALL]) is closed


def test_several_batteries_take_the_energy_weighted_soc() -> None:
    closed = _closed(
        soc_start_percent=80.0,
        soc_end_percent=82.0,
        soc_start_percent_by_ess={"a": 80.0, "b": 20.0},
        soc_end_percent_by_ess={"a": 82.0, "b": 24.0},
    )
    out = sl.with_plant_soc(closed, TWO)
    assert out["soc_start_percent"] == pytest.approx(35.0)  # (5·80 + 15·20) / 20
    assert out["soc_end_percent"] == pytest.approx(38.5)
    assert closed["soc_start_percent"] == 80.0  # input untouched


def test_several_batteries_without_soc_per_battery_have_no_soc() -> None:
    out = sl.with_plant_soc(
        _closed(
            soc_start_percent=80.0,
            soc_end_percent=82.0,
            soc_end_percent_by_ess={"a": 82.0},
        ),
        TWO,
    )
    assert "soc_start_percent" not in out
    assert "soc_end_percent" not in out


def test_chain_starts_at_the_plant_soc() -> None:
    slot = datetime(2026, 11, 18, 12, 0, tzinfo=TZ)
    closed = _closed(
        soc_start_percent=80.0,
        soc_end_percent=80.0,
        soc_start_percent_by_ess={"a": 80.0, "b": 20.0},
        soc_end_percent_by_ess={"a": 80.0, "b": 20.0},
    )
    bounds = lambda moment: (moment - timedelta(hours=6), moment + timedelta(hours=18))  # noqa: E731

    state = sl.start_chain(
        store.ledger_input_from_pending(slot, closed, None, batteries=TWO), bounds, reason="test"
    )
    assert state is not None and state.shadow_soc == pytest.approx(35.0)

    without_map = _closed(soc_start_percent=80.0, soc_end_percent=80.0)
    assert (
        sl.start_chain(
            store.ledger_input_from_pending(slot, without_map, None, batteries=TWO),
            bounds,
            reason="test",
        )
        is None
    )


# --- SoC per battery in the power interval sampler -------------------------------------------


def _plant() -> dict[str, float]:
    return {"pv": 1.0, "grid": 0.2, "battery": 0.0, "house": 1.2}


_SNAPSHOT = {
    "pv_kw": 1.0,
    "grid_kw": 0.2,
    "battery_kw": 0.0,
    "house_kw": 1.2,
    "baseload_kw": 1.2,
    "flex_sum_kw": 0.0,
    "flex_kw": {},
}


def test_sampler_logs_the_soc_of_each_battery(tmp_path) -> None:
    path = str(tmp_path / "sampler.json")
    start = datetime(2026, 11, 18, 12, 0)
    socs = iter([{"a": 80.0, "b": 20.0}, {"a": 81.0, "b": 21.0}, {"a": 82.0, "b": 24.0}])
    for minute in (0, 5, 10):
        assert sampler.tick(
            now=start + timedelta(minutes=minute),
            force=True,
            state_path=path,
            read_plant=_plant,
            read_soc=lambda: 80.0,
            read_flex_chart=dict,
            read_soc_by_id=lambda: next(socs),
        )
    closed = sampler.finalize_closed_interval(start, state_path=path)
    assert closed["soc_start_percent"] == 80.0
    assert closed["soc_start_percent_by_ess"] == {"a": 80.0, "b": 20.0}
    assert closed["soc_end_percent_by_ess"] == {"a": 82.0, "b": 24.0}


def test_sampler_without_several_batteries_logs_no_map(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [dict(SMALL)])
    path = str(tmp_path / "sampler.json")
    start = datetime(2026, 11, 18, 12, 0)
    for minute in (0, 5):
        sampler.tick(
            now=start + timedelta(minutes=minute),
            force=True,
            state_path=path,
            read_plant=_plant,
            read_soc=lambda: 50.0,
            read_flex_chart=dict,
        )
    sampler.note_decision_sample(
        _SNAPSHOT, soc_percent=50.0, soc_percent_by_ess={"a": 50.0},
        now=start + timedelta(minutes=7), state_path=path,
    )
    closed = sampler.finalize_closed_interval(start, state_path=path)
    assert "soc_start_percent_by_ess" not in closed
    assert "soc_end_percent_by_ess" not in closed


# --- start SoC of the baselines --------------------------------------------------------------


def _capture_baseline_soc(monkeypatch, batteries: list[dict]) -> dict:
    import optimizer.charge_immediate as charge_immediate
    import optimizer.filter_context as filter_context

    seen: dict = {}
    monkeypatch.setattr(config, "get_battery_params_list", lambda: list(batteries))
    monkeypatch.setattr(
        charge_immediate, "prepare_optimization_matrix", lambda m, t, consumers=None: (m, {}, t)
    )
    monkeypatch.setattr(filter_context, "resolve_filter_contexts", lambda m, c: {})

    def run(matrix, initial_soc, baseline_soc, *args, **kwargs):
        seen["initial"] = initial_soc
        seen["baseline"] = baseline_soc
        return None

    monkeypatch.setattr(sim_costs, "_run_savings_horizons", run)
    monkeypatch.setattr(sim_costs, "_assemble_savings_dict", lambda *a, **k: {})
    return seen


def test_baselines_start_at_the_plant_soc_with_several_batteries(monkeypatch) -> None:
    seen = _capture_baseline_soc(monkeypatch, TWO)
    sim_costs.calculate_optimization_savings([{}], 80.0, current_soc_by_id={"a": 80.0, "b": 20.0})
    assert seen["initial"] == 80.0
    assert seen["baseline"] == pytest.approx(35.0)


def test_baselines_start_at_the_live_soc_with_one_battery(monkeypatch) -> None:
    seen = _capture_baseline_soc(monkeypatch, [SMALL])
    sim_costs.calculate_optimization_savings([{}], 63.4, current_soc_by_id={"a": 63.4})
    assert seen["baseline"] == 63.4


def test_shadow_chain_soc_is_taken_as_is(monkeypatch) -> None:
    seen = _capture_baseline_soc(monkeypatch, TWO)
    sim_costs.calculate_optimization_savings(
        [{}], 80.0, current_soc_by_id={"a": 80.0, "b": 20.0}, baseline_initial_soc=41.0
    )
    assert seen["baseline"] == 41.0
