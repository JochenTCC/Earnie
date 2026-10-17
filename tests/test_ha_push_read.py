"""HA push-transport read path (inbox + status.json)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from house_config.ha_ehal_bindings import aggregate_ha_entities
from ehal import EHAL_SCHEMA_VERSION
from integrations.ha_adapter import HaAdapter, HaConfig, HaHttpError
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
                "sens_pv_production_active": "",
            }
        },
        "profiles": {},
    }


def test_aggregate_ha_entities_push_keeps_empty_activation():
    house = _plant_house_push_only()
    pull = aggregate_ha_entities(house, transport="pull")
    assert "sens_grid_power_active" not in pull
    weg = aggregate_ha_entities(house, transport="push")
    assert weg["sens_grid_power_active"] == ""
    assert "sens_ess_soc" not in weg


def test_read_telemetry_push_from_inbox(monkeypatch):
    table = {
        "grid.meter.sens_grid_power_active": 500.0,
        "sens_pv_production_active": 2000.0,
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
            "sens_pv_production_active": "",
        },
        transport="push",
        push_read_qids={
            "sens_grid_power_active": "grid.meter.sens_grid_power_active",
            "sens_pv_production_active": "sens_pv_production_active",
        },
    )
    adapter = HaAdapter(cfg)
    tel = adapter.read_telemetry()
    assert tel["sens_grid_power_active"] == pytest.approx(500.0)
    assert tel["sens_pv_production_active"] == pytest.approx(2000.0)
    assert "sens_ess_soc" not in tel


def test_push_fences_rest_for_push_field():
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={"sens_grid_power_active": "sensor.grid"},
        transport="push",
        push_read_qids={"sens_grid_power_active": "grid.meter.sens_grid_power_active"},
    )
    adapter = HaAdapter(cfg)
    with pytest.raises(HaHttpError, match="REST read blocked"):
        adapter.read_state("sensor.grid")


@patch("integrations.ha_adapter.requests.post")
def test_push_write_publishes_no_service(post_mock):
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
        transport="push",
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
    post_mock.assert_not_called()
    published = load_published()
    assert published["ess.house.set_ess_charge_power_limit"] == pytest.approx(3000.0)


@patch("integrations.ha_adapter.requests.get")
def test_pull_still_uses_rest(get_mock):
    def _get(url, **_kwargs):
        response = MagicMock()
        response.status_code = 200
        entity = url.rsplit("/", 1)[-1]
        payload = {
            "entity_id": entity,
            "state": "100",
            "attributes": {"unit_of_measurement": "W"},
        }
        response.json.return_value = payload
        return response

    get_mock.side_effect = _get
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={
            "sens_grid_power_active": "sensor.grid",
            "sens_pv_production_active": "sensor.pv",
        },
        transport="pull",
    )
    adapter = HaAdapter(cfg)
    tel = adapter.read_telemetry()
    assert tel["sens_grid_power_active"] == pytest.approx(100.0)
    assert "sens_ess_soc" not in tel
    assert get_mock.called
