"""HouseSim S2: vendor archetypes (units, vendor sign, split channels, fallbacks)."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from house_sim.archetype import FIXTURES_DIR, load_archetype, project_physics_to_store
from house_sim.core.archetype import base_to_native, flip_power_reading, native_to_base
from house_sim.core.physics import EssSetpoints, initial_physics, step_physics
from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest
from house_sim.stepper import setpoints_from_store
from integrations.ha_adapter import HaAdapter, HaConfig

ALL_ARCHETYPES = ("evcc_en", "fronius_de", "huawei_en", "sma_keba")
S2_ARCHETYPES = ("fronius_de", "huawei_en", "sma_keba")


def _bench(name: str):
    package = load_archetype(name)
    store = package.build_store()
    _server, base_url = start_mock_rest(
        store, host="127.0.0.1", port=0, token=DEFAULT_BENCH_TOKEN
    )
    adapter = HaAdapter(
        HaConfig(
            base_url=base_url,
            token=DEFAULT_BENCH_TOKEN,
            adapter_id="earnie-hems",
            entities=dict(package.ehal_entities),
            sign=dict(package.ehal_sign),
        )
    )
    return package, store, adapter


@pytest.fixture
def bench(request):
    yield _bench(request.param)
    stop_mock_rest()


@pytest.mark.parametrize("name", ALL_ARCHETYPES)
def test_archetype_package_is_consistent(name):
    package = load_archetype(name)
    ids = {str(e["entity_id"]) for e in package.entities}
    assert set(package.ehal_entities.values()) <= ids
    for device in package.devices:
        assert set(device["entity_ids"]) <= ids
    for eid in (package.house_params.get("derived_entities") or {}):
        assert eid in ids
    assert set(package.ehal_sign.values()) <= {"ehal", "negate"}


@pytest.mark.parametrize("name", S2_ARCHETYPES)
def test_s2_archetype_has_provenance(name):
    meta = json.loads((FIXTURES_DIR / name / "meta.json").read_text(encoding="utf-8"))
    assert meta["sources"] and meta["verified_at"]
    assert "unverified" in meta


def test_unit_conversion_roundtrip_and_dimension_guard():
    assert base_to_native(1500.0, quantity="power", unit="kw") == pytest.approx(1.5)
    assert native_to_base(1.5, quantity="power", unit="kw") == pytest.approx(1500.0)
    assert base_to_native(2.0, quantity="energy", unit="wh") == pytest.approx(2000.0)
    assert base_to_native(2.0, quantity="energy", unit="") == pytest.approx(2.0)
    with pytest.raises(ValueError):
        base_to_native(1.0, quantity="power", unit="kwh")


@pytest.mark.parametrize("bench", ALL_ARCHETYPES, indirect=True)
def test_adapter_reads_physics_in_ehal_units_and_sign(bench):
    package, store, adapter = bench
    physics = replace(
        initial_physics(package),
        pv_kw=4.2,
        ess_power_w=-1800.0,  # charging
        grid_power_w=-950.0,  # exporting
    )
    project_physics_to_store(store, package=package, physics=physics.as_dict())
    telem = adapter.read_telemetry()
    assert telem["sens_pv_production_active"] == pytest.approx(4200.0)
    assert telem["sens_grid_power_active"] == pytest.approx(-950.0)
    if "sens_ess_power" in package.ehal_entities:
        assert telem["sens_ess_power"] == pytest.approx(-1800.0)


def test_vendor_sign_is_written_inverse_for_huawei():
    package = load_archetype("huawei_en")
    store = package.build_store()
    physics = replace(initial_physics(package), ess_power_w=-1800.0, grid_power_w=-950.0)
    project_physics_to_store(store, package=package, physics=physics.as_dict())
    # Huawei: battery + = charging, meter + = export.
    assert store.numeric_state("sensor.batteries_charge_discharge_power") == pytest.approx(1800.0)
    assert store.numeric_state("sensor.power_meter_active_power") == pytest.approx(950.0)


def test_fronius_energy_counters_are_wh():
    package = load_archetype("fronius_de")
    state = initial_physics(package)
    # Fixture state 18234567 Wh → physics kWh.
    assert state.pv_energy_kwh == pytest.approx(18234.567)
    store = package.build_store()
    nxt = step_physics(state, package=package, setpoints=EssSetpoints(self_consumption=True), dt_h=0.25)
    project_physics_to_store(store, package=package, physics=nxt.as_dict())
    assert store.numeric_state("sensor.solarnet_energie_gesamt") == pytest.approx(
        nxt.pv_energy_kwh * 1000.0
    )


def test_sma_split_channels_follow_signed_physics():
    package = load_archetype("sma_keba")
    store = package.build_store()
    physics = replace(initial_physics(package), grid_power_w=-1200.0, ess_power_w=800.0)
    project_physics_to_store(store, package=package, physics=physics.as_dict())
    prefix = "sensor.sn_3012345678_"
    assert store.numeric_state(prefix + "metering_power_supplied") == pytest.approx(1200.0)
    assert store.numeric_state(prefix + "metering_power_absorbed") == pytest.approx(0.0)
    assert store.numeric_state(prefix + "battery_power_discharge_total") == pytest.approx(800.0)
    assert store.numeric_state(prefix + "battery_power_charge_total") == pytest.approx(0.0)
    # Template helper in kW.
    assert store.numeric_state("sensor.netzleistung") == pytest.approx(-1.2)


def test_setpoint_in_kw_entity_is_read_as_watts():
    package = load_archetype("sma_keba")
    store = package.build_store()
    store.set_state("input_number.batterie_sollleistung", "2.5")
    sp = setpoints_from_store(store, package)
    assert sp.active_power_w == pytest.approx(2500.0)
    assert sp.self_consumption is False


def test_grid_balance_discharge_reduces_import():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    # load 1.5 kW, pv tick1 1.2 kW, discharge 1 kW → grid 1.5 - 1.2 - 1.0 = -0.7 kW
    nxt = step_physics(
        state, package=package, setpoints=EssSetpoints(active_power_w=1000.0), dt_h=0.25
    )
    assert nxt.grid_power_w == pytest.approx(-700.0)


def test_self_consumption_without_cap_raises():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    with pytest.raises(ValueError, match="ess_max_charge_w"):
        step_physics(
            state,
            package=package,
            setpoints=EssSetpoints(self_consumption=True),
            dt_h=0.25,
        )


@pytest.mark.parametrize("name", ("fronius_de", "huawei_en"))
def test_self_consumption_fallback_without_active_setpoint(name):
    package = load_archetype(name)
    store = package.build_store()
    sp = setpoints_from_store(store, package)
    assert sp.self_consumption is True
    state = initial_physics(package)
    nxt = step_physics(state, package=package, setpoints=sp, dt_h=0.25)
    surplus_w = (nxt.pv_kw - nxt.load_kw) * 1000.0
    assert surplus_w > 0
    assert nxt.ess_power_w < 0  # charging from surplus
    assert nxt.soc_pct > state.soc_pct
    # Within limits the battery absorbs the whole surplus.
    if -nxt.ess_power_w < surplus_w:
        assert nxt.grid_power_w < 0
    else:
        assert nxt.grid_power_w == pytest.approx(0.0, abs=1e-6)


def test_self_consumption_never_overshoots_full_battery():
    package = load_archetype("huawei_en")
    state = replace(initial_physics(package), soc_pct=99.9)
    nxt = step_physics(
        state, package=package, setpoints=EssSetpoints(self_consumption=True), dt_h=0.25
    )
    assert nxt.soc_pct == pytest.approx(100.0)
    assert nxt.ess_charge_energy_kwh - state.ess_charge_energy_kwh == pytest.approx(
        0.001 * package.house_params["battery_capacity_kwh"]
    )


def test_huawei_limit_writes_succeed_without_active_setpoint():
    package, store, adapter = _bench("huawei_en")
    try:
        err = adapter.write_setpoints(
            {
                "schema_version": 3,
                "ts": "2026-01-01T00:00:00Z",
                "adapter_id": "earnie-hems",
                "set_ess_charge_power_limit": 3000.0,
                "set_ess_discharge_power_limit": 2000.0,
            }
        )
        assert err is None
        sp = setpoints_from_store(store, package)
        assert sp.charge_limit_w == pytest.approx(3000.0)
        assert sp.discharge_limit_w == pytest.approx(2000.0)
    finally:
        stop_mock_rest()


def test_mock_rejects_out_of_range_and_invalid_option():
    package = load_archetype("huawei_en")
    store = package.build_store()
    status, _ = store.apply_service(
        "number", "set_value", {"entity_id": "number.batteries_maximum_charging_power", "value": 9000}
    )
    assert status == 400
    status, _ = store.apply_service(
        "select", "select_option", {"entity_id": "select.goe_204711_frc", "option": "7"}
    )
    assert status == 400
    status, _ = store.apply_service(
        "select", "select_option", {"entity_id": "select.goe_204711_frc", "option": "2"}
    )
    assert status == 200


def test_adapter_converts_setpoint_to_kw_entity():
    package, store, adapter = _bench("sma_keba")
    try:
        err = adapter.write_setpoints(
            {
                "schema_version": 3,
                "ts": "2026-01-01T00:00:00Z",
                "adapter_id": "earnie-hems",
                "set_ess_active_power": -1500.0,
            }
        )
        assert err is None
        assert store.numeric_state("input_number.batterie_sollleistung") == pytest.approx(-1.5)
    finally:
        stop_mock_rest()


def test_flip_power_reading_swaps_w_and_kw():
    assert flip_power_reading(1.5, "kW") == pytest.approx(1500.0)
    assert flip_power_reading(1500.0, "W") == pytest.approx(1.5)
    with pytest.raises(ValueError, match="W/kW"):
        flip_power_reading(1.0, "kWh")
