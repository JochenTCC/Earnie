"""Unit tests for Loxone markers → EHAL adapter (mocked loxone_client)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ehal import EHAL_SCHEMA_VERSION
from integrations.loxone_adapter import (
    LoxoneAdapter,
    LoxoneAdapterError,
    LoxoneConfig,
    ehal_active_power_w_to_loxone_kw,
    ehal_limit_w_to_loxone_kw,
    loxone_battery_kw_to_ehal_w,
)
from integrations.loxone_comm_trace import LoxoneWriteRecord


def _pub_ok(qid, value, *, io_name=""):
    return LoxoneWriteRecord(io_name or qid, float(value), True, "t")


def _pub_fail(qid, value, *, io_name=""):
    return LoxoneWriteRecord(io_name or qid, float(value), False, "t")


def _pub_io_value_calls(mock) -> set[tuple[str, float]]:
    return {
        (str(c.kwargs.get("io_name") or ""), float(c.args[1]))
        for c in mock.call_args_list
    }


def _cfg(**kwargs) -> LoxoneConfig:
    base = dict(
        adapter_id="loxone-home",
        soc_name="SoC",
        pv_power_name="PV",
        battery_power_name="Bat",
        grid_power_name="Grid",
        charge_power_name="Charge",
        discharge_power_name="Discharge",
        active_power_name="Active",
        control_cmd_name="Cmd",
    )
    base.update(kwargs)
    return LoxoneConfig(**base)


def test_battery_sign_and_limit_units():
    # Loxone battery Merker: + = discharge, same sign as EHAL
    assert loxone_battery_kw_to_ehal_w(1.5) == pytest.approx(1500.0)
    assert loxone_battery_kw_to_ehal_w(-0.5) == pytest.approx(-500.0)
    assert ehal_limit_w_to_loxone_kw(2000) == pytest.approx(2.0)
    assert ehal_active_power_w_to_loxone_kw(-1500) == pytest.approx(-1.5)


def test_capabilities_ess_true_evcs_false():
    caps = LoxoneAdapter(_cfg()).capabilities()
    assert caps["supports_ess_write"] is True
    assert caps["supports_evcs_current"] is False


def test_capabilities_evcs_true_with_current_marker():
    caps = LoxoneAdapter(_cfg(evcs_max_current_name="EV_A")).capabilities()
    assert caps["supports_evcs_current"] is True


def test_capabilities_ess_false_without_markers():
    caps = LoxoneAdapter(
        _cfg(charge_power_name="", discharge_power_name="", active_power_name="")
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
    assert telemetry["sens_ess_soc"] == 55.0
    assert telemetry["sens_pv_production_active"] == 2000.0
    assert telemetry["sens_grid_power_active"] == 1000.0
    assert telemetry["sens_ess_power"] == pytest.approx(500.0)
    # PV 2000 + import 1000 + discharge 500
    assert telemetry["sens_power_consumers"] == pytest.approx(3500.0)


@pytest.mark.parametrize(
    ("raw", "expected_w"),
    [(3.5, 3500.0), (0.0, 0.0), (-1.0, None), (None, None)],
)
@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_read_telemetry_inbound_export_limit(fetch_mock, raw, expected_w):
    values = {"SoC": 55.0, "PV": 2.0, "Bat": 0.0, "Grid": 0.0, "ExpIn": raw}
    fetch_mock.side_effect = values.get
    telemetry = LoxoneAdapter(_cfg(grid_export_limit_in_name="ExpIn")).read_telemetry()
    assert telemetry.get("get_grid_export_power_limit") == expected_w


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_export_limit_magnitude_kw(pub_mock):
    adapter = LoxoneAdapter(_cfg(grid_export_limit_out_name="ExpOut"))
    for limit_w, expected_kw in ((0.0, 0.0), (4200.0, 4.2), (1_000_000.0, 1000.0)):
        pub_mock.reset_mock()
        error = adapter.write_setpoints(
            {
                "schema_version": EHAL_SCHEMA_VERSION,
                "ts": "2026-07-28T12:00:00Z",
                "adapter_id": "loxone-home",
                "set_grid_export_power_limit": limit_w,
            }
        )
        assert error is None
        pub_mock.assert_called_once_with(
            "set_grid_export_power_limit", expected_kw, io_name="ExpOut"
        )


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_read_telemetry_missing_raises(fetch_mock):
    fetch_mock.return_value = None
    with pytest.raises(LoxoneAdapterError):
        LoxoneAdapter(_cfg()).read_telemetry()


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_ess_kw(pub_mock):
    adapter = LoxoneAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_ess_active_power": -1500,
            "set_ess_charge_power_limit": 1500,
            "set_ess_discharge_power_limit": 2000,
        }
    )
    assert error is None
    assert pub_mock.call_count == 3
    calls = _pub_io_value_calls(pub_mock)
    assert ("Active", -1.5) in calls
    assert ("Charge", 1.5) in calls
    assert ("Discharge", 2.0) in calls


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_evcs_and_mode(pub_mock):
    adapter = LoxoneAdapter(
        _cfg(
            control_cmd_name="Cmd",
            evcs_max_current_name="EV_A",
            evcs_mode_name="EV_Modus",
        )
    )
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_ess_mode": 2,
            "set_evcs_max_current": 16,
            "set_evcs_mode": "pv",
        }
    )
    assert error is None
    calls = _pub_io_value_calls(pub_mock)
    assert ("Cmd", 2.0) in calls
    assert ("EV_A", 16.0) in calls
    assert ("EV_Modus", 1.0) in calls
    assert not [name for name, _ in calls if name in ("PVF", "NOW")]


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_evcs_mode_off(pub_mock):
    adapter = LoxoneAdapter(_cfg(evcs_max_current_name="EV_A", evcs_mode_name="EV_Modus"))
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_evcs_mode": "off",
        }
    )
    assert error is None
    assert ("EV_Modus", 0.0) in _pub_io_value_calls(pub_mock)


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_evcs_mode_now_encodes_two(pub_mock):
    adapter = LoxoneAdapter(_cfg(evcs_max_current_name="EV_A", evcs_mode_name="EV_Modus"))
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_evcs_mode": "now",
        }
    )
    assert error is None
    assert ("EV_Modus", 2.0) in _pub_io_value_calls(pub_mock)


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_evcs_mode_skipped_without_mode_marker(pub_mock):
    """Unmapped mode marker: not written and not a live-trace row; current stays usable."""
    adapter = LoxoneAdapter(_cfg(evcs_max_current_name="EV_A"))
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_evcs_mode": "pv",
            "set_evcs_max_current": 10,
        }
    )
    assert error is None
    assert adapter.last_skipped_fields() == []
    assert adapter.capabilities()["supports_evcs_current"] is True
    assert ("EV_A", 10.0) in _pub_io_value_calls(pub_mock)


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_ok)
def test_write_setpoints_ess_mode_skipped_without_cmd_marker(pub_mock):
    adapter = LoxoneAdapter(_cfg(control_cmd_name=""))
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_ess_mode": 1,
        }
    )
    assert error is None
    assert adapter.last_skipped_fields() == []
    pub_mock.assert_not_called()


@patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub_fail)
def test_write_setpoints_degrades_on_failure(pub_mock):
    adapter = LoxoneAdapter(_cfg())
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-07-28T12:00:00Z",
            "adapter_id": "loxone-home",
            "set_ess_charge_power_limit": 1000,
        }
    )
    assert error is not None
    assert "set_ess_charge_power_limit" in error["failed_fields"]
    assert adapter.capabilities()["supports_ess_write"] is False
