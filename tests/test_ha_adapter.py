"""Unit tests for Home Assistant REST → EHAL adapter (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from integrations.ha_adapter import (
    HaAdapter,
    HaConfig,
    apply_sign,
    parse_ha_numeric_state,
)


def _cfg(**kwargs) -> HaConfig:
    base = dict(
        base_url="http://homeassistant:8123",
        token="test-token",
        adapter_id="ha-home",
        entities={
            "sens_grid_power_active": "sensor.grid_power",
            "sens_pv_production_active": "sensor.pv_power",
            "sens_ess_soc": "sensor.battery_soc",
            "sens_ess_power": "sensor.battery_power",
            "sens_evcs_active_power": "sensor.evcs_power",
            "set_ess_charge_power_limit": "number.charge_limit",
            "set_ess_discharge_power_limit": "number.discharge_limit",
            "set_evcs_max_current": "number.max_current",
        },
        sign={"sens_grid_power_active": "ehal", "sens_ess_power": "negate"},
    )
    base.update(kwargs)
    return HaConfig(**base)


def _state(entity_id: str, state, unit=None):
    attrs = {}
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attrs,
    }


def test_apply_sign():
    assert apply_sign(10, "ehal") == 10.0
    assert apply_sign(10, "negate") == -10.0


def test_parse_ha_numeric_kw():
    assert parse_ha_numeric_state("1.5", unit="kW") == pytest.approx(1500.0)
    assert parse_ha_numeric_state("500", unit="W") == pytest.approx(500.0)


@patch("integrations.ha_adapter.requests.get")
def test_read_telemetry_normalizes(get_mock):
    def _get(url, **_kwargs):
        response = MagicMock()
        response.status_code = 200
        if url.endswith("sensor.grid_power"):
            response.json.return_value = _state("sensor.grid_power", "100", "W")
        elif url.endswith("sensor.pv_power"):
            response.json.return_value = _state("sensor.pv_power", "0.5", "kW")
        elif url.endswith("sensor.battery_soc"):
            response.json.return_value = _state("sensor.battery_soc", "55", "%")
        elif url.endswith("sensor.battery_power"):
            response.json.return_value = _state("sensor.battery_power", "200", "W")
        elif url.endswith("sensor.evcs_power"):
            response.json.return_value = _state("sensor.evcs_power", "1200", "W")
        else:
            response.status_code = 404
            response.json.return_value = {}
        return response

    get_mock.side_effect = _get
    adapter = HaAdapter(_cfg())
    telemetry = adapter.read_telemetry()
    assert telemetry["sens_grid_power_active"] == 100.0
    assert telemetry["sens_pv_production_active"] == 500.0
    assert telemetry["sens_ess_soc"] == 55.0
    assert telemetry["sens_ess_power"] == -200.0
    assert telemetry["sens_evcs_active_power"] == 1200.0
    assert telemetry["sens_power_consumers"] == pytest.approx(600.0)


@patch("integrations.ha_adapter.requests.post")
def test_write_setpoints_number_service(post_mock):
    response = MagicMock()
    response.status_code = 200
    post_mock.return_value = response
    adapter = HaAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": 3,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "ha-home",
            "set_ess_charge_power_limit": 1000,
            "set_ess_discharge_power_limit": 2000,
            "set_evcs_max_current": 10,
        }
    )
    assert error is None
    assert post_mock.call_count == 3
    urls = [call.args[0] for call in post_mock.call_args_list]
    assert any(url.endswith("/api/services/number/set_value") for url in urls)
    bodies = [call.kwargs["json"] for call in post_mock.call_args_list]
    values = {body["entity_id"]: body["value"] for body in bodies}
    assert values["number.charge_limit"] == 1000
    assert values["number.discharge_limit"] == 2000
    assert values["number.max_current"] == 10


@patch("integrations.ha_adapter.requests.post")
def test_write_setpoints_degrades_on_403(post_mock):
    response = MagicMock()
    response.status_code = 403
    post_mock.return_value = response
    adapter = HaAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": 3,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "ha-home",
            "set_ess_charge_power_limit": 1000,
        }
    )
    assert error is not None
    assert "set_ess_charge_power_limit" in error["failed_fields"]
    assert error["hub_status"] == "403"
    assert adapter.capabilities()["supports_ess_write"] is False


@patch("integrations.ha_adapter.requests.get")
def test_list_mappable_entities_filters_domains(get_mock):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = [
        _state("sensor.grid", "1", "W"),
        _state("number.max_current", "16", "A"),
        {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"friendly_name": "Kitchen"},
        },
    ]
    get_mock.return_value = response
    rows = HaAdapter(_cfg()).list_mappable_entities()
    ids = [row["entity_id"] for row in rows]
    assert "sensor.grid" in ids
    assert "number.max_current" in ids
    assert "light.kitchen" not in ids
