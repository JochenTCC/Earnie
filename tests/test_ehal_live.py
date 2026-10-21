"""Unit tests for thin EHAL Live façade."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ehal import EHAL_SCHEMA_VERSION
from ehal.inverter_fields import inv_field
from integrations import ehal_live
from settings.ev_power import kw_to_ampere

_WR_MAIN_PV = inv_field("wr_main", "sens_inv_power_pv")


def _live_telemetry(**extra) -> dict:
    """Plant telemetry for Live power tests (entity-scoped inv PV, no bare plant PV)."""
    doc = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-28T12:00:00Z",
        "adapter_id": "earnie-hems",
        "sens_grid_power_active": 1000.0,
        _WR_MAIN_PV: 2000.0,
        "sens_ess_power": 500.0,
    }
    doc.update(extra)
    return doc


@pytest.fixture(autouse=True)
def _isolate_live_pv_components(monkeypatch):
    """η=1 and no hub re-reads — unit tests supply inv PV on the mock telemetry."""
    components = {
        "inverters": [
            {
                "id": "wr_main",
                "ac_connection": "grid_tied",
                "efficiency": 1.0,
                "ehal_bindings": {_WR_MAIN_PV: "mapped"},
            }
        ],
        "pv_systems": [
            {"id": "test_pv", "inverter_id": "wr_main", "ehal_bindings": {}}
        ],
        "batteries": [],
    }
    monkeypatch.setattr(
        "integrations.pv_attribution.load_components_for_attribution",
        lambda: components,
    )
    monkeypatch.setattr("integrations.ehal_live.collect_scoped_pv_live_w", lambda: {})


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
    adapter.read_telemetry.return_value = _live_telemetry(adapter_id="earnie-hems")
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["battery"] == 0.5


@patch("integrations.ehal_live.get_loxone_adapter")
@patch("integrations.ehal_live.config")
def test_read_live_power_kw_loxone_backend(config_mock, adapter_factory):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "loxone",
    }.get(key, default)
    adapter = MagicMock()
    adapter.read_telemetry.return_value = _live_telemetry(adapter_id="loxone-home")
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["battery"] == 0.5
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
    adapter.read_telemetry.return_value = _live_telemetry(
        adapter_id="openems-lab", ts="2026-07-27T12:00:00Z"
    )
    adapter_factory.return_value = adapter
    power = ehal_live.read_live_power_kw()
    assert power is not None
    assert power["pv"] == 2.0
    assert power["grid"] == 1.0
    assert power["battery"] == 0.5
    # PV 2 + import 1 + discharge 0.5
    assert power["house"] == pytest.approx(3.5)


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


def _clear_safe_setpoints_skip_env() -> None:
    os.environ.pop("EARNIE_SKIP_SAFE_SETPOINTS_ON_START", None)
    os.environ.pop("EARNIE_SKIP_SAFE_SETPOINTS_ON_START", None)


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


@patch("integrations.ehal_live.write_ess_setpoints_from_control")
@patch("integrations.ehal_live.config")
def test_push_safe_setpoints_on_startup_logs_and_reraises(config_mock, ess_mock, caplog):
    # HA testbed F2: a startup crash must reach earnie.log, not only stderr.
    ehal_live.reset_adapter_cache()
    config_mock.is_loxone_silent_mode.return_value = False
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
    }.get(key, default)
    ess_mock.side_effect = ValueError("ehal.backend=ha requires EHAL_HA_BASE_URL")
    _clear_safe_setpoints_skip_env()
    with caplog.at_level("ERROR", logger=ehal_live.logger.name):
        with pytest.raises(ValueError, match="EHAL_HA_BASE_URL"):
            ehal_live.push_safe_setpoints_on_startup()
    assert any(
        "sichere Sollwerte fehlgeschlagen" in rec.getMessage() and rec.exc_info
        for rec in caplog.records
    )


@patch("integrations.ehal_live.write_flexible_consumer_states")
@patch("integrations.ehal_live.write_huawei_modbus_states")
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


@patch("integrations.loxone_client.fetch_loxone_generic_value")
def test_read_generic_value_delegates(fetch_mock):
    fetch_mock.return_value = 1.5
    assert ehal_live.read_generic_value("Earnie_X") == 1.5
    fetch_mock.assert_called_once_with("Earnie_X")


@patch("integrations.loxone_writes.send_flexible_consumer_states")
def test_write_flexible_consumer_states_delegates(send_mock):
    send_mock.return_value = []
    assert ehal_live.write_flexible_consumer_states({"a": 1.0}, None, None) == []
    send_mock.assert_called_once_with({"a": 1.0}, None, None)


@patch("integrations.loxone_writes._publish_setpoint_traced")
def test_publish_setpoint_traced_delegates(pub_mock):
    pub_mock.return_value = MagicMock(success=True)
    row = ehal_live.publish_setpoint_traced("ess.x.set_ess_active_power", 0.0, io_name="m")
    assert row.success is True
    pub_mock.assert_called_once_with(
        "ess.x.set_ess_active_power", 0.0, io_name="m"
    )


@patch("integrations.ehal_live.is_openems_backend", return_value=False)
@patch("integrations.ehal_live.is_ha_backend", return_value=False)
@patch("integrations.ehal_live_ops.read_generic_value", return_value=1.0)
def test_read_absent_mode_loxone(read_mock, _ha, _oe):
    with patch(
        "house_config.ehal_bindings.resolve_plant_binding",
        return_value="Earnie_Absent",
    ), patch(
        "house_config.profiles_store.load_default_house_profiles_doc",
        return_value={"plant": {}},
    ):
        value, bound = ehal_live.read_absent_mode()
    assert bound is True
    assert value is True
    read_mock.assert_called_once_with("Earnie_Absent")


@patch("integrations.ehal_live.is_openems_backend", return_value=False)
@patch("integrations.ehal_live.is_ha_backend", return_value=True)
@patch("integrations.ehal_live.get_ha_adapter")
def test_read_absent_mode_ha(adapter_factory, _ha, _oe):
    adapter = MagicMock()
    adapter.cfg.entities = {"sens_absent_mode": ""}
    adapter.cfg.push_read_qids = {"sens_absent_mode": "sens_absent_mode"}
    adapter.cfg.sign = {}
    adapter_factory.return_value = adapter
    with patch(
        "house_config.ehal_bindings.resolve_plant_binding",
        return_value="sens_absent_mode",
    ), patch(
        "house_config.profiles_store.load_default_house_profiles_doc",
        return_value={"plant": {"ehal_bindings": {"sens_absent_mode": ""}}},
    ), patch(
        "integrations.ha_push_read.read_push_ehal_value",
        return_value=1.0,
    ):
        value, bound = ehal_live.read_absent_mode()
    assert bound is True
    assert value is True


@patch("integrations.ehal_live.is_openems_backend", return_value=True)
@patch("integrations.ehal_live.is_ha_backend", return_value=False)
@patch("integrations.ehal_live.get_openems_adapter")
def test_read_absent_mode_openems(adapter_factory, _ha, _oe):
    adapter = MagicMock()
    adapter.read_channel.return_value = 1
    adapter_factory.return_value = adapter
    with patch(
        "house_config.ehal_bindings.resolve_plant_binding",
        return_value="ctrl/Absent",
    ), patch(
        "house_config.profiles_store.load_default_house_profiles_doc",
        return_value={"plant": {}},
    ):
        value, bound = ehal_live.read_absent_mode()
    assert bound is True
    assert value is True
    adapter.read_channel.assert_called_once_with("ctrl", "Absent")


def test_read_absent_mode_unbound():
    with patch(
        "house_config.ehal_bindings.resolve_plant_binding",
        return_value="",
    ), patch(
        "house_config.profiles_store.load_default_house_profiles_doc",
        return_value={"plant": {}},
    ):
        value, bound = ehal_live.read_absent_mode()
    assert value is None
    assert bound is False
