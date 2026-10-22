"""Unit tests for Home Assistant push adapter helpers (Binding P5e)."""
from __future__ import annotations

import pytest

from ehal import EHAL_SCHEMA_VERSION
from integrations.ha_adapter import (
    HaAdapter,
    HaConfig,
    apply_sign,
    parse_ha_field_value,
)
from integrations.ha_units import to_ehal
from runtime_store import loxone_push_inbox as inbox


@pytest.fixture(autouse=True)
def _reset_inbox():
    inbox.reset_memory_for_tests()
    yield
    inbox.reset_memory_for_tests()


@pytest.fixture(autouse=True)
def _isolate_topology_house(monkeypatch):
    empty_house = {"plant": {"ehal_bindings": {}}, "profiles": {}}
    empty_components = {"batteries": [], "inverters": [], "pv_systems": []}
    monkeypatch.setattr(
        "integrations.pv_attribution.load_house_for_attribution",
        lambda: empty_house,
    )
    monkeypatch.setattr(
        "integrations.pv_attribution.load_components_for_attribution",
        lambda: empty_components,
    )


def test_apply_sign():
    assert apply_sign(10, "ehal") == 10.0
    assert apply_sign(10, "negate") == -10.0


def test_parse_ha_field_value_power_units():
    assert parse_ha_field_value(
        "sens_grid_power_active", "1.5", unit="kW"
    ) == pytest.approx(1500.0)
    assert parse_ha_field_value(
        "sens_grid_power_active", "500", unit="W"
    ) == pytest.approx(500.0)
    assert to_ehal("sens_grid_power_active", 1.5, "kW") == pytest.approx(1500.0)


def test_capabilities_from_activation_keys():
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={
            "set_ess_charge_power_limit": "",
            "set_ess_discharge_power_limit": "",
            "set_ess_mode": "",
        },
    )
    caps = HaAdapter(cfg).capabilities()
    assert caps["supports_ess_write"] is True


def test_write_setpoints_publishes(monkeypatch):
    from integrations.ehal_write import clear_published_for_tests, load_published

    clear_published_for_tests()
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={
            "set_ess_charge_power_limit": "",
            "set_ess_discharge_power_limit": "",
            "set_ess_mode": "",
        },
        setpoint_qids={
            "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
            "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
            "set_ess_mode": "ess.house.set_ess_mode",
        },
    )
    err = HaAdapter(cfg).write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "test",
            "set_ess_charge_power_limit": 1000.0,
            "set_ess_discharge_power_limit": 2000.0,
            "set_ess_mode": 0,
        }
    )
    assert err is None
    published = load_published()
    assert published["ess.house.set_ess_charge_power_limit"] == pytest.approx(1000.0)
    assert published["ess.house.set_ess_discharge_power_limit"] == pytest.approx(2000.0)


def test_ha_ess_force_enables_capability_without_rest_write():
    """Vendor force still enables ess_active; writes go to status.json (YAML owns REST)."""
    from integrations.ehal_write import clear_published_for_tests, load_published

    clear_published_for_tests()
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={
            "set_ess_active_power": "",
            "set_ess_charge_power_limit": "",
            "set_ess_discharge_power_limit": "",
            "set_ess_mode": "",
        },
        ha_ess_force={
            "driver": "huawei_solar",
            "device_id": "dev-1",
            "duration_min": 20,
        },
        setpoint_qids={
            "set_ess_active_power": "ess.house.set_ess_active_power",
            "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
            "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
            "set_ess_mode": "ess.house.set_ess_mode",
        },
    )
    adapter = HaAdapter(cfg)
    assert adapter.capabilities()["supports_ess_write"] is True
    err = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "test",
            "set_ess_active_power": -500.0,
            "set_ess_charge_power_limit": 3000.0,
            "set_ess_discharge_power_limit": 3000.0,
            "set_ess_mode": 0,
        }
    )
    assert err is None
    published = load_published()
    assert published["ess.house.set_ess_active_power"] == pytest.approx(-500.0)


def test_export_limit_is_published_when_only_activated():
    # Regression: push bindings are activation flags (empty values); the export limit
    # was skipped as "function not available" because the check tested the value.
    from integrations.ehal_write import clear_published_for_tests, load_published

    clear_published_for_tests()
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={
            "set_ess_charge_power_limit": "",
            "set_ess_discharge_power_limit": "",
            "set_grid_export_power_limit": "",
        },
        setpoint_qids={
            "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
            "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
            "set_grid_export_power_limit": "grid.meter.set_grid_export_power_limit",
        },
    )
    adapter = HaAdapter(cfg)
    err = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "test",
            "set_ess_charge_power_limit": 1000.0,
            "set_ess_discharge_power_limit": 2000.0,
            "set_grid_export_power_limit": 4000.0,
        }
    )
    assert err is None
    assert load_published()["grid.meter.set_grid_export_power_limit"] == pytest.approx(4000.0)
    assert adapter.last_skipped_fields() == [] and adapter.last_unconfigured_fields() == []
