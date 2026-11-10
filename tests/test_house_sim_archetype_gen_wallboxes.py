"""Archetype generator with ``components.wallboxes`` (data model 6): wallbox / EV model.

Every wallbox with activated ``evcs.<id>.*`` signals and every EV runs on the HouseSim
wallbox model, so the HA testbed can plug cars in (``car_arrives``) and charge them by
Earnie's current setpoint per wallbox (multi-EV M3/M4).
"""
from __future__ import annotations

import re

import pytest

from house_sim.archetype import load_archetype
from house_sim.archetype_gen import generate_archetype, write_archetype
from house_sim.contract import fill_yaml_placeholders
from house_sim.core.physics import ScenarioOverlay
from house_sim.stepper import run_ticks
from integrations.ha_carrier_yaml import build_carrier_yaml
from tests.test_house_sim_archetype_gen import _minimal_pack

_WALLBOX_KEYS = ("set_evcs_max_current", "sens_evcs_active_power", "sens_evcs_connected")
_EV_KEYS = ("sens_evcs_soc_act", "sens_ev_connected", "sens_ev_charge_power")


def _ev(ev_id: str, *, phases: int) -> dict:
    return {
        "id": ev_id,
        "label": ev_id.upper(),
        "type": "ev",
        "battery_capacity_kwh": 60.0,
        "phases": phases,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["wb_a", "wb_b"]},
        "ehal_bindings": {key: "" for key in _EV_KEYS},
    }


def _wallbox(wb_id: str) -> dict:
    return {
        "id": wb_id,
        "label": wb_id,
        "voltage_v": 230.0,
        "phases": 3,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "unknown_vehicle": "off",
        "ehal_bindings": {key: "" for key in _WALLBOX_KEYS},
    }


def _dm6_pack() -> tuple[dict, dict]:
    house, components = _minimal_pack()
    house["profiles"][0]["consumers"] = [_ev("car_a", phases=3), _ev("car_b", phases=1)]
    components["wallboxes"] = [_wallbox("wb_a"), _wallbox("wb_b")]
    return house, components


def _load(tmp_path, pack=_dm6_pack):
    arch = generate_archetype(*pack())
    write_archetype(arch, tmp_path / "gen_wb")
    return arch, load_archetype("gen_wb", fixtures_dir=tmp_path)


def test_every_wallbox_and_ev_is_in_the_model():
    arch = generate_archetype(*_dm6_pack())
    params = arch.house_params
    assert [w["id"] for w in params["wallboxes"]] == ["wb_a", "wb_b"]
    assert [e["id"] for e in params["evs"]] == ["car_a", "car_b"]
    wb_a = params["wallboxes"][0]
    assert wb_a["read_only"] is False
    assert wb_a["entities"] == {
        "max_current": arch.placeholders["evcs.wb_a.set_evcs_max_current"],
        "power": arch.placeholders["evcs.wb_a.sens_evcs_active_power"],
        "plugged": arch.placeholders["evcs.wb_a.sens_evcs_connected"],
    }
    assert params["evs"][1]["entities"] == {
        "soc": arch.placeholders["ev.car_b.sens_evcs_soc_act"],
        "plugged": arch.placeholders["ev.car_b.sens_ev_connected"],
        "power": arch.placeholders["ev.car_b.sens_ev_charge_power"],
    }
    # The flat single-wallbox power is gone; model signals are not static.
    assert "sens_evcs_active_power" not in arch.ehal_entities["entities"]
    static = {s["ehal_id"] for s in arch.meta["static_signals"]}
    assert static.isdisjoint(arch.meta["physical_wallboxes"])
    assert arch.placeholders["evcs.wb_a.sens_evcs_connected"].startswith("binary_sensor.")
    assert arch.placeholders["ev.car_a.sens_ev_connected"].startswith("binary_sensor.")


def test_plugged_car_charges_by_the_wallbox_setpoint(tmp_path):
    arch, package = _load(tmp_path)
    store = package.build_store()
    ph = arch.placeholders
    store.set_state(ph["evcs.wb_a.set_evcs_max_current"], "10")
    store.set_state(ph["evcs.wb_b.set_evcs_max_current"], "10")
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="wb_a", ev="car_a")
    overlay.car_arrives(wallbox="wb_b", ev="car_b")
    state = run_ticks(package, store, n_ticks=1, dt_h=0.25, overlay=overlay)

    def value(ehal_id):
        return store.get(ph[ehal_id])["state"]

    # 10 A × 230 V × 3 phases; car_b charges on its single phase.
    assert float(value("evcs.wb_a.sens_evcs_active_power")) == pytest.approx(6900.0)
    assert float(value("evcs.wb_b.sens_evcs_active_power")) == pytest.approx(2300.0)
    assert value("evcs.wb_a.sens_evcs_connected") == "on"
    assert value("ev.car_a.sens_ev_connected") == "on"
    assert float(value("ev.car_b.sens_ev_charge_power")) == pytest.approx(2300.0)
    assert float(value("ev.car_a.sens_evcs_soc_act")) > 50.0
    assert state.evcs.ev_at_wallbox == {"wb_a": "car_a", "wb_b": "car_b"}


def test_free_wallbox_and_absent_car_report_unplugged(tmp_path):
    arch, package = _load(tmp_path)
    store = package.build_store()
    ph = arch.placeholders
    store.set_state(ph["evcs.wb_a.set_evcs_max_current"], "10")
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="wb_a", ev="car_a")
    run_ticks(package, store, n_ticks=1, dt_h=0.25, overlay=overlay)
    assert store.get(ph["evcs.wb_b.sens_evcs_connected"])["state"] == "off"
    assert store.get(ph["ev.car_b.sens_ev_connected"])["state"] == "off"
    assert float(store.get(ph["ev.car_b.sens_ev_charge_power"])["state"]) == 0.0


def test_wallbox_without_current_setpoint_is_read_only():
    house, components = _dm6_pack()
    del components["wallboxes"][1]["ehal_bindings"]["set_evcs_max_current"]
    arch = generate_archetype(house, components)
    wb_b = arch.house_params["wallboxes"][1]
    assert wb_b["read_only"] is True
    assert "max_current" not in wb_b["entities"]


def test_ev_without_capacity_aborts():
    house, components = _dm6_pack()
    del house["profiles"][0]["consumers"][0]["battery_capacity_kwh"]
    with pytest.raises(ValueError, match="EV 'car_a' has no battery_capacity_kwh"):
        generate_archetype(house, components)


def test_same_ev_with_other_charge_data_in_two_profiles_aborts():
    house, components = _dm6_pack()
    other = {"id": "efh2", "consumers": [_ev("car_a", phases=1)]}
    house["profiles"].append(other)
    with pytest.raises(ValueError, match="different charge data"):
        generate_archetype(house, components)


def test_ev_initial_soc_is_an_explicit_argument():
    arch = generate_archetype(*_dm6_pack(), ev_initial_soc_pct=30.0)
    assert {e["initial_soc_pct"] for e in arch.house_params["evs"]} == {30.0}
    assert arch.meta["params"]["ev_initial_soc_pct"] == {"value": 30.0, "source": "argument"}


def test_no_entity_placeholder_left_after_fill():
    house, components = _dm6_pack()
    arch = generate_archetype(house, components)
    raw = build_carrier_yaml(house, components, earnie_host="h", earnie_port=8541, token="t", repeat_s=10.0)
    filled = fill_yaml_placeholders(raw, arch.placeholders)
    assert not re.search(r"ENTITY_\w+", filled)
    assert arch.placeholders["evcs.wb_b.sens_evcs_connected"] in filled


def test_car_plug_state_is_pushed_as_a_digital_signal():
    """The carrier pushes the car's binary_sensor plug state like the wallbox's (on → 1)."""
    house, components = _dm6_pack()
    raw = build_carrier_yaml(house, components, earnie_host="h", earnie_port=8541, token="t", repeat_s=10.0)
    for qid in ("ev_car_a_sens_ev_connected", "evcs_wb_a_sens_evcs_connected"):
        block = raw.split(f"id: earnie_push_{qid}", 1)[1].split("  - id:", 1)[0]
        assert "is_state(" in block, qid
