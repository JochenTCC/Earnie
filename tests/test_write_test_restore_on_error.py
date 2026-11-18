"""Schreibtest: safe setpoints are restored even when the roundtrip aborts.

A forced probe (e.g. ``set_ess_active_power`` -5000 W) must not stay on the plant when the
dispatch raises after a first publish, or when a Streamlit rerun / stop interrupts the wait
or the read-back. A bad batch (unknown charger, unbound flex field) fails before anything
is written.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException

from integrations import ehal_live
from integrations import ehal_write_test as ewt
from integrations.ehal_write import load_published
from integrations.ha_adapter import HaAdapter, HaConfig

FORCED = {"set_ess_active_power": -100.0}
ESS_QID = "ess.house.set_ess_charge_power_limit"
EVCS_QID = "evcs.e_auto.set_evcs_max_current"
HEATPUMP_QID = "heatpump.waermepumpe.set_enable"


@pytest.fixture
def loud_mode():
    with patch.object(ewt.config, "is_silent_mode", return_value=False):
        yield


def _roundtrip(**kwargs):
    return ewt.roundtrip_batch(
        FORCED,
        force_ess_active=True,
        wait_s=0.1,
        max_power_kw=5.0,
        ev_nominal_a=16.0,
        **kwargs,
    )


@pytest.mark.usefixtures("loud_mode")
@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.write_probes")
def test_dispatch_error_after_write_restores_and_propagates(write_mock, restore_mock):
    write_mock.side_effect = ValueError("kein E-Auto mit Ladepunkt 'x'")
    with pytest.raises(ValueError, match="Ladepunkt"):
        _roundtrip()
    restore_mock.assert_called_once()


@pytest.mark.usefixtures("loud_mode")
@pytest.mark.parametrize("control_exc", [StopException(), RerunException(None)])
@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.write_probes")
@patch("integrations.ehal_write_test.time.sleep")
def test_streamlit_control_flow_during_wait_restores(
    sleep_mock, write_mock, restore_mock, control_exc
):
    write_mock.return_value = (None, dict(FORCED))
    sleep_mock.side_effect = control_exc
    with pytest.raises(type(control_exc)):
        _roundtrip()
    restore_mock.assert_called_once()


@pytest.mark.usefixtures("loud_mode")
@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.read_back")
@patch("integrations.ehal_write_test.write_probes")
@patch("integrations.ehal_write_test.time.sleep")
def test_streamlit_stop_during_read_back_restores(
    sleep_mock, write_mock, read_mock, restore_mock
):
    del sleep_mock
    write_mock.return_value = (None, dict(FORCED))
    read_mock.side_effect = StopException()
    with pytest.raises(StopException):
        _roundtrip()
    restore_mock.assert_called_once()


@pytest.mark.usefixtures("loud_mode")
@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.write_probes")
def test_failing_restore_is_logged_and_keeps_original_error(
    write_mock, restore_mock, caplog
):
    write_mock.side_effect = ValueError("original")
    restore_mock.side_effect = OSError("restore down")
    with caplog.at_level(logging.CRITICAL, logger="integrations.ehal_write_test"):
        with pytest.raises(ValueError, match="original"):
            _roundtrip()
    critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert critical and "restore FAILED" in critical[0].getMessage()
    assert "restore down" in caplog.text


@pytest.mark.usefixtures("loud_mode")
@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.write_probes")
def test_no_restore_when_restore_disabled(write_mock, restore_mock):
    write_mock.side_effect = ValueError("boom")
    with pytest.raises(ValueError):
        _roundtrip(restore=False)
    restore_mock.assert_not_called()


@pytest.mark.usefixtures("loud_mode")
@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test._dispatch_probe_writes")
def test_clamp_error_writes_nothing_and_does_not_restore(dispatch_mock, restore_mock):
    result = ewt.roundtrip_batch(
        FORCED, force_ess_active=False, wait_s=0.0, max_power_kw=5.0
    )
    assert result.status == ewt.RoundtripStatus.FAIL
    dispatch_mock.assert_not_called()
    restore_mock.assert_not_called()


@patch("integrations.ehal_write_test.restore_safe_setpoints")
@patch("integrations.ehal_write_test.write_probes")
def test_silent_switched_on_before_write_does_not_restore(write_mock, restore_mock):
    write_mock.side_effect = ewt.WriteTestSilentError("silent")
    with patch.object(ewt.config, "is_silent_mode", return_value=False):
        with pytest.raises(ewt.WriteTestSilentError):
            _roundtrip()
    restore_mock.assert_not_called()


# --- Pre-validation in _dispatch_probe_writes (real HA adapter, publish ledger) ---


@pytest.fixture
def ha_adapter(monkeypatch: pytest.MonkeyPatch) -> HaAdapter:
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="test",
            entities={ESS_QID: "", EVCS_QID: ""},
            setpoint_qids={ESS_QID: ESS_QID, HEATPUMP_QID: HEATPUMP_QID, EVCS_QID: EVCS_QID},
        )
    )
    monkeypatch.setattr(ewt.config, "is_silent_mode", lambda: False)
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "is_openems_backend", lambda: False)
    monkeypatch.setattr(ehal_live, "is_ehal_network_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "get_ha_adapter", lambda: adapter)
    monkeypatch.setattr(ehal_live, "get_adapter", lambda: adapter)
    monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
    monkeypatch.setattr(
        ehal_live,
        "live_ev_consumers",
        lambda: [{"id": "e_auto", "type": "ev", "charger_id": "e_auto", "charging_schedule": {}}],
    )
    return adapter


@pytest.mark.usefixtures("ha_adapter")
def test_unknown_charger_fails_before_any_publish() -> None:
    with pytest.raises(ewt.WriteTestBatchError, match="other_wb"):
        ewt.write_probes(
            {ESS_QID: 1500.0, "evcs.other_wb.set_evcs_max_current": 6.0},
            max_power_kw=10.0,
            ev_nominal_a=16.0,
        )
    assert ESS_QID not in load_published()


@pytest.mark.usefixtures("ha_adapter")
def test_unbound_flex_field_fails_before_any_publish() -> None:
    with pytest.raises(ewt.WriteTestBatchError, match="pool.pool_filter.set_enable"):
        ewt.write_probes(
            {ESS_QID: 1500.0, "pool.pool_filter.set_enable": 1}, max_power_kw=10.0
        )
    assert ESS_QID not in load_published()


@pytest.mark.usefixtures("ha_adapter")
@patch("integrations.ehal_write_test.restore_safe_setpoints")
def test_rejected_batch_in_roundtrip_writes_nothing_and_does_not_restore(restore_mock):
    with pytest.raises(ewt.WriteTestBatchError, match="pool.pool_filter.set_enable"):
        ewt.roundtrip_batch(
            {ESS_QID: 1500.0, "pool.pool_filter.set_enable": 1},
            wait_s=0.0,
            max_power_kw=10.0,
        )
    assert ESS_QID not in load_published()
    restore_mock.assert_not_called()


def test_batch_error_stays_a_value_error_for_the_ui() -> None:
    """The Schreibtest UI catches ``ValueError``; the new error must still match."""
    assert issubclass(ewt.WriteTestBatchError, ValueError)


@pytest.mark.usefixtures("ha_adapter")
def test_valid_mixed_batch_still_publishes_all_rows() -> None:
    error, _ = ewt.write_probes(
        {ESS_QID: 1500.0, HEATPUMP_QID: 1, EVCS_QID: 6.0},
        max_power_kw=10.0,
        ev_nominal_a=16.0,
    )
    assert error is None
    published = load_published()
    assert published[ESS_QID] == pytest.approx(1500.0)
    assert published[HEATPUMP_QID] == pytest.approx(1.0)
    assert published[EVCS_QID] == pytest.approx(6.0)
