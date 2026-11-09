"""Unit tests for OpenEMS REST → EHAL adapter (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from integrations.openems_adapter import (
    OpenemsAdapter,
    OpenemsConfig,
    ehal_charge_limit_to_openems,
    ehal_discharge_limit_to_openems,
    evcs_amps_to_watts,
    openems_grid_to_ehal_w,
)


def _cfg(**kwargs) -> OpenemsConfig:
    base = dict(
        base_url="http://edge:8084",
        username="x",
        password="admin",
        adapter_id="openems-lab",
    )
    base.update(kwargs)
    return OpenemsConfig(**base)


def _ok_response(value):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"value": value}
    return response


def test_grid_sign_flip():
    assert openems_grid_to_ehal_w(-77) == 77.0
    assert openems_grid_to_ehal_w(50) == -50.0


def test_ess_limit_mapping():
    assert ehal_charge_limit_to_openems(2000) == -2000.0
    assert ehal_discharge_limit_to_openems(1500) == 1500.0


def test_evcs_amps_to_watts():
    assert evcs_amps_to_watts(16, voltage_v=230, phases=1) == pytest.approx(3680.0)
    assert evcs_amps_to_watts(16, voltage_v=230, phases=3) == pytest.approx(11040.0)


@patch("integrations.openems_adapter.requests.get")
def test_read_telemetry_normalizes(get_mock):
    def _get(url, **_kwargs):
        response = MagicMock()
        response.status_code = 200
        if "GridActivePower" in url:
            response.json.return_value = {"value": -100}
        elif "ProductionActivePower" in url:
            response.json.return_value = {"value": 500}
        elif "/Soc" in url or url.endswith("Soc"):
            response.json.return_value = {"value": 55}
        elif "evcs0" in url and "ActivePower" in url:
            response.json.return_value = {"value": 1200}
        elif "ActivePower" in url:
            response.json.return_value = {"value": 200}
        else:
            response.json.return_value = {"value": None}
        return response

    get_mock.side_effect = _get
    adapter = OpenemsAdapter(_cfg(evcs_channels=(("e_auto", "evcs0", "SetChargePowerLimit"),)))
    telemetry = adapter.read_telemetry()
    assert telemetry["sens_grid_power_active"] == 100.0
    assert "sens_pv_production_active" not in telemetry
    assert "sens_ess_soc" not in telemetry
    assert adapter.read_ess_soc_pct() == pytest.approx(55.0)
    assert telemetry["sens_ess_power"] == 200.0
    assert telemetry["sens_evcs_active_power"] == 1200.0
    # Plant AC PV from _sum (500) + import 100 + discharge 200
    assert telemetry["sens_power_consumers"] == pytest.approx(800.0)


_TWO_CHARGERS = (
    ("auto_a", "evcs0", "SetChargePowerLimit"),
    ("auto_b", "evcs1", "SetChargePowerLimit"),
)


def _evcs_setpoint(amps: float) -> dict:
    return {
        "schema_version": 4,
        "ts": "2026-07-27T12:00:00Z",
        "adapter_id": "openems-lab",
        "set_evcs_max_current": amps,
    }


@patch("integrations.openems_adapter.requests.post")
def test_write_setpoints_ess(post_mock):
    post_mock.return_value = _ok_response(None)
    adapter = OpenemsAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": 4,
            "ts": "2026-07-27T12:00:00Z",
            "adapter_id": "openems-lab",
            "set_ess_active_power": -1500,
            "set_ess_charge_power_limit": 1000,
            "set_ess_discharge_power_limit": 2000,
        },
    )
    assert error is None
    assert post_mock.call_count == 3
    bodies = [call.kwargs["json"]["value"] for call in post_mock.call_args_list]
    assert -1500 in bodies  # Equals
    assert -1000 in bodies
    assert 2000 in bodies


def test_write_setpoints_rejects_evcs_fields():
    adapter = OpenemsAdapter(_cfg())
    with pytest.raises(ValueError, match="write_evcs_setpoints"):
        adapter.write_setpoints(_evcs_setpoint(10))


@patch("integrations.openems_adapter.requests.post")
def test_each_charger_writes_its_own_component(post_mock):
    post_mock.return_value = _ok_response(None)
    adapter = OpenemsAdapter(_cfg(evcs_channels=_TWO_CHARGERS))
    assert adapter.write_evcs_setpoints("auto_a", _evcs_setpoint(10), voltage_v=230, phases=1) is None
    assert adapter.write_evcs_setpoints("auto_b", _evcs_setpoint(16), voltage_v=230, phases=3) is None
    calls = [(call.args[0], call.kwargs["json"]["value"]) for call in post_mock.call_args_list]
    assert any("evcs0/SetChargePowerLimit" in url and value == 2300 for url, value in calls)
    assert any("evcs1/SetChargePowerLimit" in url and value == 11040 for url, value in calls)


@patch("integrations.openems_adapter.requests.post")
def test_a_failing_charger_does_not_stop_the_other(post_mock):
    def _post(url, **_kwargs):
        response = MagicMock()
        response.status_code = 403 if "evcs0" in url else 200
        response.json.return_value = {"value": None}
        return response

    post_mock.side_effect = _post
    adapter = OpenemsAdapter(_cfg(evcs_channels=_TWO_CHARGERS))
    error = adapter.write_evcs_setpoints("auto_a", _evcs_setpoint(10), voltage_v=230, phases=1)
    assert error is not None and error["failed_fields"] == ["set_evcs_max_current"]
    assert adapter.write_evcs_setpoints("auto_b", _evcs_setpoint(10), voltage_v=230, phases=1) is None
    # auto_a stays disabled, auto_b keeps writing.
    post_mock.reset_mock()
    adapter.write_evcs_setpoints("auto_a", _evcs_setpoint(10), voltage_v=230, phases=1)
    adapter.write_evcs_setpoints("auto_b", _evcs_setpoint(10), voltage_v=230, phases=1)
    assert [("evcs1" in call.args[0]) for call in post_mock.call_args_list] == [True]
    assert adapter.capabilities()["supports_evcs_current"] is True


def test_charger_without_openems_address_is_skipped():
    adapter = OpenemsAdapter(_cfg(evcs_channels=_TWO_CHARGERS))
    assert adapter.write_evcs_setpoints("auto_c", _evcs_setpoint(10), voltage_v=230, phases=1) is None
    assert adapter.last_skipped_fields() == ["set_evcs_max_current"]


@patch("integrations.openems_adapter.requests.post")
def test_write_lock_degrades_ess(post_mock):
    response = MagicMock()
    response.status_code = 403
    post_mock.return_value = response
    adapter = OpenemsAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": 4,
            "ts": "2026-07-27T12:00:00Z",
            "adapter_id": "openems-lab",
            "set_ess_charge_power_limit": 500,
        }
    )
    assert error is not None
    assert "set_ess_charge_power_limit" in error["failed_fields"]
    assert error["hub_status"] == "403"
    caps = adapter.capabilities()
    assert caps["supports_ess_write"] is False
