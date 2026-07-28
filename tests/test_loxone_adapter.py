"""Unit tests for Loxone markers → EHAL adapter (mocked loxone_client)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from integrations.loxone_adapter import (
    LoxoneAdapter,
    LoxoneAdapterError,
    LoxoneConfig,
    ehal_limit_w_to_loxone_kw,
    loxone_battery_kw_to_ehal_w,
)


def _cfg(**kwargs) -> LoxoneConfig:
    base = dict(
        adapter_id="loxone-home",
        soc_name="SoC",
        pv_power_name="PV",
        battery_power_name="Bat",
        grid_power_name="Grid",
        charge_power_name="Charge",
        discharge_power_name="Discharge",
    )
    base.update(kwargs)
    return LoxoneConfig(**base)


def test_battery_sign_and_limit_units():
    assert loxone_battery_kw_to_ehal_w(1.5) == pytest.approx(-1500.0)
    assert loxone_battery_kw_to_ehal_w(-0.5) == pytest.approx(500.0)
    assert ehal_limit_w_to_loxone_kw(2000) == pytest.approx(2.0)


def test_capabilities_ess_true_evcs_false():
    caps = LoxoneAdapter(_cfg()).capabilities()
    assert caps["supports_ess_write"] is True
    assert caps["supports_evcs_current"] is False


def test_capabilities_ess_false_without_markers():
    caps = LoxoneAdapter(
        _cfg(charge_power_name="", discharge_power_name="")
    ).capabilities()
    assert caps["supports_ess_write"] is False


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_read_telemetry_normalizes(fetch_mock):
    def _fetch(name: str):
        return {
            "SoC": 55.0,
            "PV": 2.0,
            "Bat": 0.5,
            "Grid": 1.0,
        }.get(name)

    fetch_mock.side_effect = _fetch
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    assert telemetry["ess_soc"] == 55.0
    assert telemetry["pv_production_active"] == 2000.0
    assert telemetry["grid_power_active"] == 1000.0
    assert telemetry["ess_power"] == pytest.approx(-500.0)


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_read_telemetry_missing_raises(fetch_mock):
    fetch_mock.return_value = None
    with pytest.raises(LoxoneAdapterError):
        LoxoneAdapter(_cfg()).read_telemetry()


@patch("integrations.loxone_adapter.loxone_client.send_loxone_value")
def test_write_setpoints_ess_kw(send_mock):
    send_mock.return_value = True
    adapter = LoxoneAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": 1,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_ess_charge_power_limit": 1500,
            "set_ess_discharge_power_limit": 2000,
            "set_evcs_max_current": 10,
        }
    )
    assert error is None
    assert send_mock.call_count == 2
    calls = {(c.args[0], c.args[1]) for c in send_mock.call_args_list}
    assert ("Charge", 1.5) in calls
    assert ("Discharge", 2.0) in calls


@patch("integrations.loxone_adapter.loxone_client.send_loxone_value")
def test_write_setpoints_degrades_on_failure(send_mock):
    send_mock.return_value = False
    adapter = LoxoneAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": 1,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_ess_charge_power_limit": 1000,
        }
    )
    assert error is not None
    assert "set_ess_charge_power_limit" in error["failed_fields"]
    assert adapter.capabilities()["supports_ess_write"] is False
