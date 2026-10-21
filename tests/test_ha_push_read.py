"""HA push-transport read path (inbox + status.json)."""
from __future__ import annotations

import pytest

from house_config.ha_ehal_bindings import aggregate_ha_entities
from ehal import EHAL_SCHEMA_VERSION
from integrations.ha_adapter import HaAdapter, HaConfig
from runtime_store import loxone_push_inbox as inbox


@pytest.fixture(autouse=True)
def _reset_inbox():
    inbox.reset_memory_for_tests()
    yield
    inbox.reset_memory_for_tests()


@pytest.fixture(autouse=True)
def _isolate_topology_house(monkeypatch):
    """Avoid local house_profiles / components leaking into Topology P2."""
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


def _plant_house_push_only() -> dict:
    return {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
            }
        },
        "profiles": {},
    }


def test_aggregate_ha_entities_keeps_empty_activation():
    house = _plant_house_push_only()
    aggregated = aggregate_ha_entities(house)
    assert aggregated["sens_grid_power_active"] == ""
    assert "sens_pv_production_active" not in aggregated
    assert "sens_ess_soc" not in aggregated


def test_read_telemetry_push_from_inbox(monkeypatch):
    table = {
        "grid.meter.sens_grid_power_active": 500.0,
    }

    def _fake_read(qid: str, **_kw):
        if qid in table:
            return table[qid], inbox.STATE_OK
        return None, inbox.STATE_READ_ERROR

    monkeypatch.setattr("integrations.ha_push_read.read_push_value", _fake_read)

    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={
            "sens_grid_power_active": "",
        },
        push_read_qids={
            "sens_grid_power_active": "grid.meter.sens_grid_power_active",
        },
    )
    adapter = HaAdapter(cfg)
    tel = adapter.read_telemetry()
    assert tel["sens_grid_power_active"] == pytest.approx(500.0)
    assert "sens_pv_production_active" not in tel
    assert "sens_ess_soc" not in tel


def test_push_write_publishes_no_service():
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
    adapter = HaAdapter(cfg)
    err = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "test",
            "set_ess_charge_power_limit": 3000.0,
            "set_ess_discharge_power_limit": 3000.0,
            "set_ess_mode": 0,
        }
    )
    assert err is None
    published = load_published()
    assert published["ess.house.set_ess_charge_power_limit"] == pytest.approx(3000.0)


def test_write_setpoints_warns_when_hub_reports_unapplied(caplog):
    # HA testbed F22: "published" is not "applied"; HA pushes hub_write_failed.
    from ehal.push_signals import HUB_WRITE_FAILED_ID
    from integrations.ehal_write import clear_published_for_tests

    clear_published_for_tests()
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={"set_ess_charge_power_limit": "", "set_ess_discharge_power_limit": ""},
        setpoint_qids={
            "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
            "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
        },
    )
    adapter = HaAdapter(cfg)
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-01-01T00:00:00Z",
        "adapter_id": "test",
        "set_ess_charge_power_limit": 3000.0,
        "set_ess_discharge_power_limit": 3000.0,
    }
    with caplog.at_level("WARNING"):
        assert adapter.write_setpoints(setpoint) is None
    assert not any("hub_write_failed" in r.getMessage() for r in caplog.records)

    inbox.record_push(HUB_WRITE_FAILED_ID, "1")
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert adapter.write_setpoints(setpoint) is None
    assert any("hub_write_failed" in r.getMessage() for r in caplog.records)


def test_write_records_omit_never_activated_fields():
    # HA testbed F19: set_ess_mode is not activated, nothing is written — no "Ja" row.
    from integrations.ehal_live_records import build_ehal_write_records

    rows = build_ehal_write_records(
        {"set_ess_charge_power_limit": 0.0, "set_ess_mode": 2.0},
        written_at="t",
        error=None,
        unconfigured=["set_ess_mode"],
    )
    assert [r["field"] for r in rows] == ["set_ess_charge_power_limit"]


def test_adapter_reports_never_activated_fields_as_unconfigured():
    from integrations.ehal_write import clear_published_for_tests

    clear_published_for_tests()
    cfg = HaConfig(
        base_url="",
        token="",
        adapter_id="test",
        entities={"set_ess_charge_power_limit": "", "set_ess_discharge_power_limit": ""},
        setpoint_qids={
            "set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit",
            "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
        },
    )
    adapter = HaAdapter(cfg)
    err = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-01-01T00:00:00Z",
            "adapter_id": "test",
            "set_ess_charge_power_limit": 3000.0,
            "set_ess_discharge_power_limit": 3000.0,
            "set_ess_mode": 0,
        }
    )
    assert err is None
    assert "set_ess_mode" in adapter.last_unconfigured_fields()
    assert "set_ess_mode" not in adapter.last_skipped_fields()
