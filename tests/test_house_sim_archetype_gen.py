"""HouseSim archetype generator (HA Testbed P1): pack → loadable archetype."""
from __future__ import annotations

import copy
import json
import re

import pytest

from house_sim.archetype import load_archetype
from house_sim.archetype_gen import (
    ARCHETYPE_FILES,
    generate_archetype,
    write_archetype,
)
from house_sim.core.archetype import physics_entity_values
from house_sim.stepper import run_ticks
from integrations.ha_carrier_yaml import build_carrier_yaml
from house_sim.contract import fill_yaml_placeholders
from scripts import house_sim_archetype_gen as cli


def _minimal_pack() -> tuple[dict, dict]:
    house = {
        "plant": {"ehal_bindings": {"sens_grid_power_active": ""}},
        "profiles": [{"id": "efh", "annual_kwh": 4380, "consumers": []}],
    }
    components = {
        "batteries": [
            {
                "id": "house",
                "type": "house",
                "battery_capacity_kwh": 10.0,
                "battery_max_charge_power_kw": 5.0,
                "battery_max_discharge_power_kw": 4.0,
                "inverter_id": "wr_main",
                "ehal_bindings": {
                    "ess.house.sens_ess_soc": "",
                    "ess.house.sens_ess_power": "",
                    "ess.house.set_ess_active_power": "",
                    "ess.house.set_ess_charge_power_limit": "",
                    "ess.house.set_ess_discharge_power_limit": "",
                },
            }
        ],
        "inverters": [
            {
                "id": "wr_main",
                "type": "hybrid",
                "ac_connection": "grid_tied",
                "control": "read_only",
                "ehal_bindings": {"inv.wr_main.sens_inv_power_pv": ""},
            }
        ],
        "pv_systems": [{"id": "roof", "kwp": 10.0, "inverter_id": "wr_main", "ehal_bindings": {}}],
    }
    return house, components


def _full_pack() -> tuple[dict, dict]:
    house, components = _minimal_pack()
    house["plant"]["ehal_bindings"].update(
        {
            "sens_grid_energy_import": "",
            "sens_grid_energy_export": "",
            "sens_pv_energy": "",
            "sens_temperature_outside": "",
            "get_grid_export_power_limit": "",
            "set_grid_export_power_limit": "",
        }
    )
    house["profiles"][0]["consumers"] = [
        {
            "id": "e_auto",
            "type": "ev",
            "ehal_bindings": {
                "sens_evcs_active_power": "",
                "sens_evcs_connected": "",
                "set_evcs_max_current": "",
            },
        },
        {
            "id": "waermepumpe",
            "type": "thermal_annual",
            "ehal_bindings": {"sens_heating_active": "", "sens_temperature_heat_storage": ""},
        },
        {
            "id": "pool_filter",
            "type": "thermal_rc",
            "ehal_bindings": {"sens_filter_active": "", "sens_temperature_water": ""},
        },
    ]
    bat = components["batteries"][0]
    bat["battery_min_soc"] = 10.0
    bat["battery_max_soc"] = 100.0
    bat["ehal_bindings"].update(
        {
            "ess.house.sens_ess_energy_charge": "",
            "ess.house.sens_ess_energy_discharge": "",
            "ess.house.get_ess_soc_min": "",
            "ess.house.get_ess_max_charge_power": "",
        }
    )
    components["inverters"][0]["control"] = "full"
    components["inverters"][0]["ehal_bindings"].update(
        {"inv.wr_main.sens_inv_power_ac": "", "inv.wr_main.set_inv_ac_power_limit": ""}
    )
    return house, components


def _signal_ids(arch) -> set[str]:
    return {s.ehal_id for s in arch.bundle.read_signals + arch.bundle.write_signals}


@pytest.mark.parametrize("pack", [_minimal_pack, _full_pack], ids=["minimal", "full"])
def test_every_activated_signal_has_unique_entity(pack):
    arch = generate_archetype(*pack())
    assert set(arch.placeholders) == _signal_ids(arch)
    ids = [e["entity_id"] for e in arch.entities["entities"]]
    assert len(ids) == len(set(ids)) == len(arch.placeholders)
    assert sorted(arch.placeholders.values()) == sorted(ids)
    device_ids = [i for d in arch.entities["devices"] for i in d["entity_ids"]]
    assert sorted(device_ids) == sorted(ids)


@pytest.mark.parametrize("pack", [_minimal_pack, _full_pack], ids=["minimal", "full"])
def test_written_archetype_loads_and_runs_physics(pack, tmp_path):
    arch = generate_archetype(*pack())
    out = tmp_path / "gen_case"
    written = write_archetype(arch, out)
    assert sorted(p.name for p in written) == sorted(ARCHETYPE_FILES)

    package = load_archetype("gen_case", fixtures_dir=tmp_path)
    store = package.build_store()
    assert set(package.ehal_entities.values()) <= {e["entity_id"] for e in package.entities}

    soc_id = package.ehal_entities["sens_ess_soc"]
    store.set_state(package.ehal_entities["set_ess_active_power"], "-2000")
    state = run_ticks(package, store, n_ticks=6, dt_h=0.25)
    # Charging at 2 kW for 1.5 h on 10 kWh raises SoC by ~30 points.
    assert state.soc_pct == pytest.approx(80.0, abs=0.01)
    assert float(store.get(soc_id)["state"]) == pytest.approx(state.soc_pct, abs=0.01)
    values = physics_entity_values(package, state.as_dict())
    assert package.ehal_entities["sens_grid_power_active"] in values
    assert package.ehal_entities["sens_pv_production_active"] in values


def test_battery_energy_counters_are_physical(tmp_path):
    arch = generate_archetype(*_full_pack())
    write_archetype(arch, tmp_path / "gen_full")
    package = load_archetype("gen_full", fixtures_dir=tmp_path)
    energy = package.house_params["battery_energy_entities"]
    assert energy["charge"] == arch.placeholders["ess.house.sens_ess_energy_charge"]
    store = package.build_store()
    store.set_state(package.ehal_entities["set_ess_active_power"], "-2000")
    run_ticks(package, store, n_ticks=2, dt_h=0.25)
    assert float(store.get(energy["charge"])["state"]) == pytest.approx(1.0, abs=1e-3)


def test_non_physical_signals_are_static_and_listed_in_meta():
    arch = generate_archetype(*_full_pack())
    listed = {s["ehal_id"] for s in arch.meta["static_signals"]}
    physical = {p["ehal_id"] for p in arch.meta["physical"].values()}
    energy = {"ess.house.sens_ess_energy_charge", "ess.house.sens_ess_energy_discharge"}
    assert listed.isdisjoint(physical)
    assert listed | physical | energy == _signal_ids(arch)
    assert "heatpump.waermepumpe.sens_heating_active" in listed
    by_id = {s["ehal_id"]: s for s in arch.meta["static_signals"]}
    # Battery limits come from the pack, not from a table.
    assert by_id["ess.house.get_ess_max_charge_power"]["value"] == "5000"
    assert by_id["ess.house.get_ess_soc_min"]["value"] == "10"
    states = {e["entity_id"]: e for e in arch.entities["entities"]}
    temp = states[by_id["pool.pool_filter.sens_temperature_water"]["entity_id"]]
    assert temp["attributes"]["unit_of_measurement"] == "°C"
    # Physical limits start at the battery maximum, not at 0.
    assert states[arch.placeholders["ess.house.set_ess_charge_power_limit"]]["state"] == "5000"
    assert states[arch.placeholders["ess.house.set_ess_discharge_power_limit"]]["state"] == "4000"


@pytest.mark.parametrize("pack", [_minimal_pack, _full_pack], ids=["minimal", "full"])
def test_no_entity_placeholder_left_after_fill(pack):
    house, components = pack()
    arch = generate_archetype(house, components)
    raw = build_carrier_yaml(house, components, earnie_host="h", earnie_port=8541, token="t", repeat_s=10.0)
    assert re.search(r"ENTITY_\w+", raw)
    filled = fill_yaml_placeholders(raw, arch.placeholders)
    assert not re.search(r"ENTITY_\w+", filled)
    for entity_id in arch.placeholders.values():
        assert entity_id in filled


def test_read_only_battery_uses_self_consumption_with_explicit_caps():
    house, components = _minimal_pack()
    for key in list(components["batteries"][0]["ehal_bindings"]):
        if key.endswith(("set_ess_active_power", "set_ess_charge_power_limit", "set_ess_discharge_power_limit")):
            del components["batteries"][0]["ehal_bindings"][key]
    arch = generate_archetype(house, components)
    assert arch.house_params["ess_fallback"] == "self_consumption"
    assert arch.house_params["ess_max_charge_w"] == 5000.0
    assert arch.house_params["ess_max_discharge_w"] == 4000.0


def test_generation_is_deterministic():
    a = generate_archetype(*_full_pack())
    b = generate_archetype(*_full_pack())
    assert a.files() == b.files()
    changed_house, changed_components = _full_pack()
    changed_components["batteries"][0]["battery_capacity_kwh"] = 12.0
    assert generate_archetype(changed_house, changed_components).meta["source_pack_sha256"] != a.meta["source_pack_sha256"]


# --- fail loud ---------------------------------------------------------------


def test_missing_battery_capacity_aborts_and_argument_fixes_it():
    house, components = _minimal_pack()
    del components["batteries"][0]["battery_capacity_kwh"]
    with pytest.raises(ValueError, match="battery_capacity_kwh"):
        generate_archetype(house, components)
    arch = generate_archetype(house, components, battery_kwh=8.0)
    assert arch.house_params["battery_capacity_kwh"] == 8.0
    assert arch.meta["params"]["battery_capacity_kwh"]["source"] == "argument"


def test_missing_load_aborts_without_profile_or_argument():
    house, components = _minimal_pack()
    house["profiles"][0].pop("annual_kwh")
    with pytest.raises(ValueError, match="base load"):
        generate_archetype(house, components)
    assert generate_archetype(house, components, load_kw=1.2).house_params["load_kw"] == 1.2


def test_missing_pv_kwp_aborts():
    house, components = _minimal_pack()
    components["pv_systems"][0].pop("kwp")
    with pytest.raises(ValueError, match="kwp"):
        generate_archetype(house, components)


def test_non_canonical_plant_pv_aborts():
    house, components = _minimal_pack()
    house["plant"]["ehal_bindings"]["sens_pv_production_active"] = ""
    with pytest.raises(ValueError, match="not canonical"):
        generate_archetype(house, components)


def test_inverter_with_pv_but_no_pv_signal_aborts():
    house, components = _minimal_pack()
    components["inverters"][0]["ehal_bindings"] = {}
    with pytest.raises(ValueError, match="not canonical"):
        generate_archetype(house, components)


def test_grid_tied_battery_without_ess_power_aborts():
    house, components = _minimal_pack()
    del components["batteries"][0]["ehal_bindings"]["ess.house.sens_ess_power"]
    with pytest.raises(ValueError, match="sens_ess_power"):
        generate_archetype(house, components)


def test_stored_entity_id_aborts():
    house, components = _minimal_pack()
    house["plant"]["ehal_bindings"]["sens_grid_power_active"] = "sensor.real"
    with pytest.raises(ValueError, match="must not store entity_id"):
        generate_archetype(house, components)


def test_two_pv_sources_abort():
    house, components = _minimal_pack()
    components["inverters"].append(
        {"id": "wr_2", "type": "pv", "ehal_bindings": {"inv.wr_2.sens_inv_power_pv": ""}}
    )
    with pytest.raises(ValueError, match="one PV source"):
        generate_archetype(house, components)


def test_unknown_static_kind_aborts_unless_overridden():
    house, components = _minimal_pack()
    house["plant"]["ehal_bindings"]["get_evcs_ready_by_time"] = ""
    with pytest.raises(ValueError, match="no static value"):
        generate_archetype(copy.deepcopy(house), components)
    arch = generate_archetype(house, components, static_overrides={"get_evcs_ready_by_time": "07:00"})
    assert any(s["source"] == "override" for s in arch.meta["static_signals"])


def test_static_unit_must_match_quantity():
    house, components = _minimal_pack()
    house["plant"]["ehal_bindings"]["get_grid_export_power_limit"] = ""
    arch = generate_archetype(house, components)
    entity = next(
        e for e in arch.entities["entities"]
        if e["entity_id"] == arch.placeholders["grid.meter.get_grid_export_power_limit"]
    )
    assert entity["attributes"]["unit_of_measurement"] == "W"


# --- CLI ---------------------------------------------------------------------


def _write_pack(tmp_path, pack):
    house, components = pack
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "house_profiles.json").write_text(json.dumps(house), encoding="utf-8")
    (cfg / "components.json").write_text(json.dumps(components), encoding="utf-8")
    return cfg


def test_cli_writes_archetype(tmp_path, capsys):
    cfg = _write_pack(tmp_path, _full_pack())
    out = tmp_path / "out" / "case"
    assert cli.main(["--config-dir", str(cfg), "--out", str(out)]) == 0
    assert "signals" in capsys.readouterr().out
    assert load_archetype("case", fixtures_dir=out.parent).entities


def test_cli_reports_error_and_writes_nothing(tmp_path, capsys):
    house, components = _minimal_pack()
    del components["batteries"][0]["battery_capacity_kwh"]
    cfg = _write_pack(tmp_path, (house, components))
    out = tmp_path / "out"
    assert cli.main(["--config-dir", str(cfg), "--out", str(out)]) == 2
    assert "battery_capacity_kwh" in capsys.readouterr().err
    assert not out.exists()


def test_cli_battery_kwh_and_static_arguments(tmp_path):
    house, components = _minimal_pack()
    del components["batteries"][0]["battery_capacity_kwh"]
    house["plant"]["ehal_bindings"]["get_evcs_ready_by_time"] = ""
    cfg = _write_pack(tmp_path, (house, components))
    out = tmp_path / "out"
    args = ["--config-dir", str(cfg), "--out", str(out), "--battery-kwh", "7", "--static", "get_evcs_ready_by_time=07:00"]
    assert cli.main(args) == 0
    assert json.loads((out / "house_params.json").read_text(encoding="utf-8"))["battery_capacity_kwh"] == 7.0
