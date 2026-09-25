"""Unit tests for EHAL-Com write-test helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ehal import EHAL_SCHEMA_VERSION
from integrations import ehal_write_test as ewt


@pytest.fixture
def loud_mode():
    with patch.object(ewt.config, "is_silent_mode", return_value=False):
        yield


@pytest.fixture
def silent_mode():
    with patch.object(ewt.config, "is_silent_mode", return_value=True):
        yield


def test_clamp_rejects_active_power_without_force():
    with pytest.raises(ewt.WriteTestClampError, match="Force"):
        ewt.clamp_probe_value(
            "set_ess_active_power",
            100.0,
            max_power_kw=5.0,
            force_ess_active=False,
        )


def test_clamp_rejects_oversized_active_power(loud_mode):
    del loud_mode
    with pytest.raises(ewt.WriteTestClampError, match="200"):
        ewt.clamp_probe_value(
            "set_ess_active_power",
            500.0,
            max_power_kw=5.0,
            force_ess_active=True,
        )


def test_clamp_accepts_tiny_active_power():
    assert ewt.clamp_probe_value(
        "set_ess_active_power",
        -150.0,
        max_power_kw=5.0,
        force_ess_active=True,
    ) == pytest.approx(-150.0)


def test_clamp_rejects_oversized_limit():
    with pytest.raises(ewt.WriteTestClampError, match="0…5000"):
        ewt.clamp_probe_value(
            "set_ess_charge_power_limit",
            6000.0,
            max_power_kw=5.0,
        )


def test_clamp_rejects_oversized_ev_current():
    with pytest.raises(ewt.WriteTestClampError, match="0…6"):
        ewt.clamp_probe_value(
            "set_evcs_max_current",
            10.0,
            max_power_kw=5.0,
            ev_nominal_a=16.0,
        )


def test_clamp_ev_uses_lower_nominal():
    assert ewt.clamp_probe_value(
        "set_evcs_max_current",
        3.0,
        max_power_kw=5.0,
        ev_nominal_a=3.0,
    ) == pytest.approx(3.0)
    with pytest.raises(ewt.WriteTestClampError, match="0…3"):
        ewt.clamp_probe_value(
            "set_evcs_max_current",
            4.0,
            max_power_kw=5.0,
            ev_nominal_a=3.0,
        )


def test_writes_allowed_respects_silent():
    with patch.object(ewt.config, "is_silent_mode", return_value=True):
        assert ewt.writes_allowed() is False
        with pytest.raises(ewt.WriteTestSilentError):
            ewt.assert_writes_allowed()
    with patch.object(ewt.config, "is_silent_mode", return_value=False):
        assert ewt.writes_allowed() is True


def test_write_probe_blocked_when_silent(silent_mode):
    del silent_mode
    with pytest.raises(ewt.WriteTestSilentError):
        ewt.write_probe("set_ess_mode", 0, max_power_kw=5.0)


def test_values_match_tolerance():
    assert ewt.values_match(1000.0, 1000.5) is True
    assert ewt.values_match(1000.0, 1020.0) is False
    assert ewt.values_match(0, 0) is True
    assert ewt.values_match("off", "OFF") is True


@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.read_back")
@patch("integrations.ehal_write_test.write_probes")
@patch("integrations.ehal_write_test.time.sleep")
def test_roundtrip_pass(sleep_mock, write_mock, read_mock, restore_mock, loud_mode):
    del loud_mode
    write_mock.return_value = (None, {"set_evcs_max_current": 0.0})
    read_mock.return_value = 0.0
    result = ewt.roundtrip(
        "set_evcs_max_current",
        0.0,
        wait_s=0.1,
        max_power_kw=5.0,
        ev_nominal_a=6.0,
    )
    assert result.status == ewt.RoundtripStatus.PASS
    sleep_mock.assert_called_once()
    restore_mock.assert_called_once()


@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.read_back")
@patch("integrations.ehal_write_test.write_probes")
@patch("integrations.ehal_write_test.time.sleep")
def test_roundtrip_fail_mismatch(sleep_mock, write_mock, read_mock, restore_mock, loud_mode):
    del loud_mode, sleep_mock
    write_mock.return_value = (None, {"set_evcs_max_current": 0.0})
    read_mock.return_value = 99.0
    result = ewt.roundtrip(
        "set_evcs_max_current",
        0.0,
        wait_s=0.0,
        max_power_kw=5.0,
        ev_nominal_a=6.0,
    )
    assert result.status == ewt.RoundtripStatus.FAIL
    restore_mock.assert_called_once()


@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.read_back")
@patch("integrations.ehal_write_test.write_probes")
@patch("integrations.ehal_write_test.time.sleep")
def test_roundtrip_partial_no_echo(sleep_mock, write_mock, read_mock, restore_mock, loud_mode):
    del loud_mode, sleep_mock
    write_mock.return_value = (None, {"set_ess_charge_power_limit": 1000.0})
    read_mock.return_value = None
    result = ewt.roundtrip(
        "set_ess_charge_power_limit",
        1000.0,
        wait_s=0.0,
        max_power_kw=5.0,
    )
    assert result.status == ewt.RoundtripStatus.PARTIAL
    restore_mock.assert_called_once()


@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.read_back")
@patch("integrations.ehal_write_test.write_probes")
@patch("integrations.ehal_write_test.time.sleep")
def test_roundtrip_batch_writes_once(sleep_mock, write_mock, read_mock, restore_mock, loud_mode):
    del loud_mode, sleep_mock
    write_mock.return_value = (
        None,
        {"set_ess_mode": 0, "set_evcs_max_current": 0.0},
    )
    read_mock.side_effect = [0, 0.0]
    result = ewt.roundtrip_batch(
        {"set_ess_mode": 0, "set_evcs_max_current": 0.0},
        wait_s=0.0,
        max_power_kw=5.0,
        ev_nominal_a=6.0,
    )
    assert result.status == ewt.RoundtripStatus.PASS
    write_mock.assert_called_once()
    assert len(result.field_results) == 2
    restore_mock.assert_called_once()


@patch("integrations.ehal_write_test.ehal_live")
def test_write_probes_builds_multi_setpoint(ehal_live_mock, loud_mode):
    del loud_mode
    adapter = MagicMock()
    adapter.cfg.adapter_id = "test-adapter"
    adapter.write_setpoints.return_value = None
    ehal_live_mock.get_adapter.return_value = adapter
    with patch.object(ewt.config, "get_battery_params", return_value={"max_power_kw": 5.0}):
        err, clamped = ewt.write_probes(
            {"set_ess_mode": 1, "set_ess_charge_power_limit": 1000.0},
            max_power_kw=5.0,
        )
    assert err is None
    assert clamped["set_ess_mode"] == 1
    setpoint = adapter.write_setpoints.call_args[0][0]
    assert setpoint["set_ess_mode"] == 1
    assert setpoint["set_ess_charge_power_limit"] == 1000.0


def test_roundtrip_silent_short_circuits(silent_mode):
    del silent_mode
    result = ewt.roundtrip("set_ess_mode", 0, wait_s=0.0)
    assert result.status == ewt.RoundtripStatus.SILENT


@patch("integrations.ehal_write_test.ehal_live")
def test_restore_calls_network_push(ehal_live_mock, loud_mode):
    del loud_mode
    ehal_live_mock.is_ehal_network_backend.return_value = True
    ewt.restore_safe_setpoints()
    ehal_live_mock._push_safe_setpoints_network.assert_called_once()
    ehal_live_mock._push_safe_setpoints_loxone.assert_not_called()


@patch("integrations.ehal_write_test.mapped_write_targets")
def test_allowed_probe_fields_force_gate(mapped_mock):
    mapped_mock.return_value = {
        "set_ess_active_power": "number.ess",
        "set_ess_mode": "number.mode",
        "set_ess_charge_power_limit": "number.charge",
    }
    without = ewt.allowed_probe_fields(force_ess_active=False)
    assert "set_ess_active_power" not in without
    assert "set_ess_mode" in without
    with_force = ewt.allowed_probe_fields(force_ess_active=True)
    assert with_force[0] == "set_ess_active_power"


@patch("integrations.ehal_write_test.ehal_live")
def test_write_probe_builds_setpoint(ehal_live_mock, loud_mode):
    del loud_mode
    adapter = MagicMock()
    adapter.cfg.adapter_id = "test-adapter"
    adapter.write_setpoints.return_value = None
    ehal_live_mock.get_adapter.return_value = adapter
    with patch.object(ewt.config, "get_battery_params", return_value={"max_power_kw": 5.0}):
        err = ewt.write_probe("set_ess_mode", 0, max_power_kw=5.0)
    assert err is None
    setpoint = adapter.write_setpoints.call_args[0][0]
    assert setpoint["schema_version"] == EHAL_SCHEMA_VERSION
    assert setpoint["set_ess_mode"] == 0
    assert setpoint["adapter_id"] == "test-adapter"


@patch("integrations.ehal_write_test.ehal_live")
def test_read_back_ha_numeric(ehal_live_mock):
    ehal_live_mock.is_ha_backend.return_value = True
    ehal_live_mock.is_openems_backend.return_value = False
    adapter = MagicMock()
    adapter.cfg.entities = {"set_ess_charge_power_limit": "number.charge_limit"}
    adapter.read_state.return_value = {
        "state": "1500",
        "attributes": {"unit_of_measurement": "W"},
    }
    ehal_live_mock.get_ha_adapter.return_value = adapter
    assert ewt.read_back("set_ess_charge_power_limit") == pytest.approx(1500.0)
