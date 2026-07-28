"""Unit tests for thin EHAL Live façade."""
from __future__ import annotations

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
        "grid_power_active": 1000.0,
        "pv_production_active": 2000.0,
        "ess_soc": 50.0,
        "ess_power": 500.0,
    }
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["battery"] == -0.5


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
        "grid_power_active": 1000.0,
        "pv_production_active": 2000.0,
        "ess_soc": 50.0,
        "ess_power": 500.0,
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
def test_write_ess_limits_persists_error(config_mock, adapter_factory, persist_mock):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
        "EHAL_ADAPTER_ID": "openems-lab",
    }.get(key, default)
    adapter = MagicMock()
    adapter.cfg.adapter_id = "openems-lab"
    adapter.write_setpoints.return_value = {
        "schema_version": 1,
        "ts": "2026-07-27T12:00:00Z",
        "adapter_id": "openems-lab",
        "failed_fields": ["set_ess_charge_power_limit"],
        "message": "HTTP 403",
        "retryable": True,
        "hub_status": "403",
    }
    adapter_factory.return_value = adapter
    error, records = ehal_live.write_ess_limits_from_huawei(1, 1.5)
    assert error is not None
    assert records
    assert records[0]["success"] is False
    persist_mock.assert_called_once()
    args = adapter.write_setpoints.call_args[0][0]
    assert args["set_ess_charge_power_limit"] == 1500.0
    assert args["set_ess_discharge_power_limit"] == 0.0
