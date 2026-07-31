"""Unit tests for thin EHAL Live façade."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ehal import EHAL_SCHEMA_VERSION
from integrations import ehal_live
from settings.ev_power import kw_to_ampere


def test_kw_to_ampere_roundtrip():
    amps = kw_to_ampere(3.68, voltage_v=230, phases=1)
    assert amps == pytest.approx(16.0)


@patch("integrations.ehal_live.config")
def test_is_openems_backend(config_mock):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
    }.get(key, default)
    assert ehal_live.is_openems_backend() is True
    assert ehal_live.is_ehal_network_backend() is True


@patch("integrations.ehal_live.get_ha_adapter")
@patch("integrations.ehal_live.config")
def test_read_live_power_kw_ha_backend(config_mock, adapter_factory):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "ha",
    }.get(key, default)
    adapter = MagicMock()
    adapter.read_telemetry.return_value = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-28T12:00:00Z",
        "adapter_id": "ha-home",
        "sens_grid_power_active": 1000.0,
        "sens_pv_production_active": 2000.0,
        "sens_ess_soc": 50.0,
        "sens_ess_power": 500.0,
    }
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["battery"] == -0.5


@patch("integrations.ehal_live.get_loxone_adapter")
@patch("integrations.ehal_live.config")
def test_read_live_power_kw_loxone_backend(config_mock, adapter_factory):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "loxone",
    }.get(key, default)
    adapter = MagicMock()
    adapter.read_telemetry.return_value = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-28T12:00:00Z",
        "adapter_id": "loxone-home",
        "sens_grid_power_active": 1000.0,
        "sens_pv_production_active": 2000.0,
        "sens_ess_soc": 50.0,
        "sens_ess_power": 500.0,
    }
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["battery"] == -0.5
    assert ehal_live.is_loxone_backend() is True
    assert ehal_live.is_ehal_network_backend() is False


@patch("integrations.ehal_live.get_openems_adapter")
@patch("integrations.ehal_live.config")
def test_read_live_power_kw_sign(config_mock, adapter_factory):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
    }.get(key, default)
    adapter = MagicMock()
    adapter.read_telemetry.return_value = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-27T12:00:00Z",
        "adapter_id": "openems-lab",
        "sens_grid_power_active": 1000.0,
        "sens_pv_production_active": 2000.0,
        "sens_ess_soc": 50.0,
        "sens_ess_power": 500.0,
    }
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["grid"] == 1.0
    assert power["battery"] == -0.5
    assert power["house"] == pytest.approx(2.5)


@patch("integrations.ehal_live.persist_write_error")
@patch("integrations.ehal_live.get_openems_adapter")
@patch("integrations.ehal_live.config")
def test_write_ess_setpoints_persists_error(config_mock, adapter_factory, persist_mock):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
        "EHAL_ADAPTER_ID": "openems-lab",
    }.get(key, default)
    config_mock.get_battery_params.return_value = {"max_power_kw": 5.0}
    adapter = MagicMock()
    adapter.cfg.adapter_id = "openems-lab"
    adapter.write_setpoints.return_value = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-27T12:00:00Z",
        "adapter_id": "openems-lab",
        "failed_fields": ["set_ess_charge_power_limit"],
        "message": "HTTP 403",
        "retryable": True,
        "hub_status": "403",
    }
    adapter_factory.return_value = adapter
    error, records = ehal_live.write_ess_setpoints_from_control(1, 1.5)
    assert error is not None
    assert records
    assert records[0]["success"] is False
    persist_mock.assert_called_once()
    args = adapter.write_setpoints.call_args[0][0]
    assert args["set_ess_active_power"] == -1500.0
    assert args["set_ess_charge_power_limit"] == 5000.0
    assert args["set_ess_discharge_power_limit"] == 0.0
    assert "set_ess_mode" in args


def test_clamp_ess_test_target_kw():
    assert ehal_live.clamp_ess_test_target_kw(3.0, max_power_kw=5.0) == 3.0
    assert ehal_live.clamp_ess_test_target_kw(9.0, max_power_kw=5.0) == 5.0
    assert ehal_live.clamp_ess_test_target_kw(-2.0, max_power_kw=5.0) == 2.0
    assert ehal_live.clamp_ess_test_target_kw(1.5, max_power_kw=0.0) == 1.5


@patch("integrations.ehal_live.write_ess_setpoints_from_control")
@patch("integrations.ehal_live.config")
def test_force_write_ess_test_setpoints_network(config_mock, write_mock):
    ehal_live.reset_adapter_cache()
    config_mock.is_loxone_silent_mode.return_value = False
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
    }.get(key, default)
    config_mock.get_battery_params.return_value = {"max_power_kw": 5.0}
    write_mock.return_value = (None, [{"field": "set_ess_mode", "success": True}])
    err, records, backend = ehal_live.force_write_ess_test_setpoints(1, 1.5)
    assert err is None
    assert backend == "OpenEMS"
    assert records
    write_mock.assert_called_once_with(1, 1.5, 5.0)


@patch("integrations.ehal_live.loxone_client.send_huawei_modbus_states")
@patch("integrations.ehal_live.config")
def test_force_write_ess_test_setpoints_loxone(config_mock, send_mock):
    from integrations.loxone_comm_trace import LoxoneWriteRecord

    ehal_live.reset_adapter_cache()
    config_mock.is_loxone_silent_mode.return_value = False
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "loxone",
    }.get(key, default)
    config_mock.get_battery_params.return_value = {"max_power_kw": 5.0}
    send_mock.return_value = [
        LoxoneWriteRecord("Earnie_Steuerbefehl", 0.0, True, "2026-07-31T06:00:00")
    ]
    err, records, backend = ehal_live.force_write_ess_test_setpoints(0, 1.0)
    assert err is None
    assert backend == "Loxone"
    assert records[0]["io_name"] == "Earnie_Steuerbefehl"
    send_mock.assert_called_once_with(0, 1.0, 0.0)


@patch("integrations.ehal_live.config")
def test_force_write_ess_test_setpoints_silent(config_mock):
    config_mock.is_loxone_silent_mode.return_value = True
    err, records, backend = ehal_live.force_write_ess_test_setpoints(1, 1.0)
    assert err is not None
    assert "Silent" in err
    assert records == []
    assert backend == "silent"


def _clear_safe_setpoints_skip_env() -> None:
    os.environ.pop("EARNIE_SKIP_SAFE_SETPOINTS_ON_START", None)
    os.environ.pop("ENERGY_OPTIMIZER_SKIP_SAFE_SETPOINTS_ON_START", None)


@patch("integrations.ehal_live.write_evcs_max_current_from_consumers")
@patch("integrations.ehal_live.write_ess_setpoints_from_control")
@patch("integrations.ehal_live.config")
def test_push_safe_setpoints_on_startup_network(config_mock, ess_mock, evcs_mock):
    ehal_live.reset_adapter_cache()
    config_mock.is_loxone_silent_mode.return_value = False
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
    }.get(key, default)
    ess_mock.return_value = (None, [])
    evcs_mock.return_value = (None, [])
    _clear_safe_setpoints_skip_env()
    ehal_live.push_safe_setpoints_on_startup()
    ess_mock.assert_called_once_with(0, 0.0)
    evcs_mock.assert_called_once_with({})


@patch("integrations.ehal_live.loxone_client.send_flexible_consumer_states")
@patch("integrations.ehal_live.loxone_client.send_huawei_modbus_states")
@patch("integrations.ehal_live.config")
def test_push_safe_setpoints_on_startup_loxone(config_mock, huawei_mock, flex_mock):
    ehal_live.reset_adapter_cache()
    config_mock.is_loxone_silent_mode.return_value = False
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "loxone",
    }.get(key, default)
    huawei_mock.return_value = []
    flex_mock.return_value = []
    _clear_safe_setpoints_skip_env()
    ehal_live.push_safe_setpoints_on_startup()
    huawei_mock.assert_called_once_with(0, 0.0, 0.0)
    flex_mock.assert_called_once_with({}, None, None)


@patch("integrations.ehal_live.write_ess_setpoints_from_control")
@patch("integrations.ehal_live.config")
def test_push_safe_setpoints_on_startup_silent(config_mock, ess_mock):
    config_mock.is_loxone_silent_mode.return_value = True
    _clear_safe_setpoints_skip_env()
    ehal_live.push_safe_setpoints_on_startup()
    ess_mock.assert_not_called()


@patch("integrations.ehal_live.write_ess_setpoints_from_control")
@patch("integrations.ehal_live.config")
def test_push_safe_setpoints_on_startup_skip_env(config_mock, ess_mock):
    config_mock.is_loxone_silent_mode.return_value = False
    with patch.dict("os.environ", {"EARNIE_SKIP_SAFE_SETPOINTS_ON_START": "1"}):
        ehal_live.push_safe_setpoints_on_startup()
    ess_mock.assert_not_called()
