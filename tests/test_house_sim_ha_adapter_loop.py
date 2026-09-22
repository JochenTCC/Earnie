"""HaAdapter against live house_sim mock: read/write, degrade, closed loop."""
from __future__ import annotations

import pytest

from house_sim.archetype import load_archetype, project_physics_to_store
from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest
from house_sim.stepper import initial_physics, step_physics
from integrations.ha_adapter import HaAdapter, HaConfig, HaHttpError


@pytest.fixture
def bench():
    package = load_archetype("evcc_en")
    store = package.build_store()
    physics = initial_physics(package)
    project_physics_to_store(store, package=package, physics=physics.as_dict())
    _server, base_url = start_mock_rest(
        store, host="127.0.0.1", port=0, token=DEFAULT_BENCH_TOKEN
    )
    cfg = HaConfig(
        base_url=base_url,
        token=DEFAULT_BENCH_TOKEN,
        adapter_id="earnie-hems",
        entities=dict(package.ehal_entities),
        sign=dict(package.ehal_sign),
    )
    adapter = HaAdapter(cfg)
    yield package, store, physics, adapter, base_url
    stop_mock_rest()


def test_read_telemetry_units_via_mock(bench):
    _package, _store, _physics, adapter, _base = bench
    telem = adapter.read_telemetry()
    # PV entity is kW 0.8 → W 800
    assert telem["sens_pv_production_active"] == pytest.approx(800.0)
    assert telem["sens_ess_soc"] == pytest.approx(55.0)
    assert telem["sens_grid_power_active"] == pytest.approx(0.0)


def test_unavailable_required_raises(bench):
    _package, store, _physics, adapter, _base = bench
    store.set_state("sensor.evcc_battery_soc", "unavailable")
    with pytest.raises((HaHttpError, ValueError)):
        adapter.read_telemetry()


def test_unknown_optional_skipped(bench):
    _package, store, _physics, adapter, _base = bench
    store.set_state("sensor.evcc_battery_power", "unknown")
    telem = adapter.read_telemetry()
    assert "sens_ess_power" not in telem or telem.get("sens_ess_power") is None


def test_write_setpoints_updates_mock(bench):
    _package, store, _physics, adapter, _base = bench
    err = adapter.write_setpoints(
        {
            "schema_version": 3,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "earnie-hems",
            "set_ess_active_power": -1500.0,
            "set_ess_charge_power_limit": 5000.0,
            "set_ess_discharge_power_limit": 5000.0,
        }
    )
    assert err is None
    assert store.numeric_state("input_number.ess_active_power_w") == pytest.approx(
        -1500.0
    )
    payload = adapter.read_state("input_number.ess_active_power_w")
    assert float(payload["state"]) == pytest.approx(-1500.0)


def test_switch_write_domain_rejected_by_adapter(bench):
    package, _store, _physics, _adapter, base_url = bench
    bad = HaAdapter(
        HaConfig(
            base_url=base_url,
            token=DEFAULT_BENCH_TOKEN,
            adapter_id="earnie-hems",
            entities={
                **package.ehal_entities,
                "set_ess_active_power": "switch.evcc_loadpoint_1_enable",
            },
            sign=dict(package.ehal_sign),
        )
    )
    err = bad.write_setpoints(
        {
            "schema_version": 3,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "earnie-hems",
            "set_ess_active_power": 1.0,
        }
    )
    assert err is not None
    assert "Unsupported write domain" in err["message"]


def test_write_error_degrades_ess_capability(bench):
    _package, store, _physics, adapter, _base = bench
    assert adapter.capabilities()["supports_ess_write"] is True
    store.force_service_status(403)
    err = adapter.write_setpoints(
        {
            "schema_version": 3,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "earnie-hems",
            "set_ess_active_power": -1000.0,
        }
    )
    assert err is not None
    assert adapter.capabilities()["supports_ess_write"] is False
    assert adapter.last_write_error() is not None
    store.force_service_status(None)


def test_closed_loop_charge_moves_soc(bench):
    package, store, physics, adapter, _base = bench
    err = adapter.write_setpoints(
        {
            "schema_version": 3,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "earnie-hems",
            "set_ess_active_power": -2000.0,
            "set_ess_charge_power_limit": 5000.0,
            "set_ess_discharge_power_limit": 5000.0,
        }
    )
    assert err is None
    soc_before = adapter.read_telemetry()["sens_ess_soc"]
    nxt = physics
    for _ in range(3):
        nxt = step_physics(nxt, package=package, store=store, dt_h=0.25)
        project_physics_to_store(store, package=package, physics=nxt.as_dict())
    telem = adapter.read_telemetry()
    assert telem["sens_ess_soc"] > soc_before
    # PV series advanced from tick 0 → 3
    assert telem["sens_pv_production_active"] == pytest.approx(
        package.pv_series_kw[3] * 1000.0
    )
