"""Contract parity: OpenEMS / HA / Loxone via ehal_live (config switch only)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ehal import EHAL_SCHEMA_VERSION, validate_capabilities
from integrations import ehal_live


_FIXTURE_TELEMETRY = {
    "schema_version": EHAL_SCHEMA_VERSION,
    "ts": "2026-07-28T12:00:00Z",
    "adapter_id": "contract",
    "grid_power_active": 1000.0,
    "pv_production_active": 2000.0,
    "ess_soc": 50.0,
    "ess_power": 500.0,
    "evcs_active_power": 1200.0,
}

_FIXTURE_CAPABILITIES = {
    "schema_version": EHAL_SCHEMA_VERSION,
    "ts": "2026-07-28T12:00:00Z",
    "adapter_id": "contract",
    "supports_ess_write": True,
    "supports_evcs_current": True,
}


def _config_side_effect(backend: str):
    values = {
        "EHAL_BACKEND": backend,
        "EHAL_ADAPTER_ID": "contract",
        "EHAL_OPENEMS_BASE_URL": "http://openems-edge:8084",
        "EHAL_OPENEMS_USERNAME": "x",
        "EHAL_OPENEMS_PASSWORD": "admin",
        "EHAL_OPENEMS_ESS_COMPONENT": "ess0",
        "EHAL_OPENEMS_EVCS_COMPONENT": "evcs0",
        "EHAL_HA_BASE_URL": "http://homeassistant:8123",
        "EHAL_HA_TOKEN": "token",
        "EHAL_HA_ENTITIES": {
            "grid_power_active": "sensor.grid",
            "pv_production_active": "sensor.pv",
            "ess_soc": "sensor.soc",
            "ess_power": "sensor.ess",
            "set_ess_charge_power_limit": "number.charge",
            "set_ess_discharge_power_limit": "number.discharge",
            "set_evcs_max_current": "number.max_a",
        },
        "EHAL_HA_SIGN": {},
        "GLOBAL_TIMEOUT": 10,
    }

    def _get(key, default=None):
        return values.get(key, default)

    return _get


def test_live_power_identical_when_only_backend_switches():
    ehal_live.reset_adapter_cache()
    adapter = MagicMock()
    adapter.read_telemetry.return_value = dict(_FIXTURE_TELEMETRY)

    with patch("integrations.ehal_live.config") as config_mock, patch(
        "integrations.ehal_live.get_openems_adapter", return_value=adapter
    ):
        config_mock.get.side_effect = _config_side_effect("openems")
        openems_power = ehal_live.read_live_power_kw()

    ehal_live.reset_adapter_cache()
    with patch("integrations.ehal_live.config") as config_mock, patch(
        "integrations.ehal_live.get_ha_adapter", return_value=adapter
    ):
        config_mock.get.side_effect = _config_side_effect("ha")
        ha_power = ehal_live.read_live_power_kw()

    ehal_live.reset_adapter_cache()
    with patch("integrations.ehal_live.config") as config_mock, patch(
        "integrations.ehal_live.get_loxone_adapter", return_value=adapter
    ):
        config_mock.get.side_effect = _config_side_effect("loxone")
        loxone_power = ehal_live.read_live_power_kw()

    assert openems_power == ha_power == loxone_power
    assert openems_power is not None
    assert openems_power["pv"] == 2.0
    assert openems_power["grid"] == 1.0
    assert openems_power["battery"] == -0.5
    assert openems_power["house"] == pytest.approx(2.5)


def test_get_adapter_routes_by_ehal_backend_only():
    ehal_live.reset_adapter_cache()
    openems = MagicMock(name="openems")
    ha = MagicMock(name="ha")
    loxone = MagicMock(name="loxone")

    cases = (
        ("openems", "integrations.ehal_live.get_openems_adapter", openems),
        ("ha", "integrations.ehal_live.get_ha_adapter", ha),
        ("loxone", "integrations.ehal_live.get_loxone_adapter", loxone),
        ("", "integrations.ehal_live.get_loxone_adapter", loxone),
    )
    for backend, factory_path, expected in cases:
        ehal_live.reset_adapter_cache()
        with patch("integrations.ehal_live.config") as config_mock, patch(
            factory_path, return_value=expected
        ) as factory:
            config_mock.get.side_effect = _config_side_effect(backend)
            assert ehal_live.get_adapter() is expected
            factory.assert_called_once()


def test_ess_setpoint_payload_identical_when_only_backend_switches():
    ehal_live.reset_adapter_cache()
    captured: list[dict] = []

    def _capture_write(setpoint, **_kwargs):
        captured.append(dict(setpoint))
        return None

    adapter = MagicMock()
    adapter.cfg.adapter_id = "contract"
    adapter.write_setpoints.side_effect = _capture_write

    with patch("integrations.ehal_live.persist_write_error"), patch(
        "integrations.ehal_live.config"
    ) as config_mock, patch(
        "integrations.ehal_live.get_openems_adapter", return_value=adapter
    ), patch(
        "integrations.ehal_live.loxone_client.map_huawei_modbus_values",
        return_value=(1.5, 0.0, 0),
    ):
        config_mock.get.side_effect = _config_side_effect("openems")
        ehal_live.write_ess_limits_from_huawei(1, 1.5)

    ehal_live.reset_adapter_cache()
    with patch("integrations.ehal_live.persist_write_error"), patch(
        "integrations.ehal_live.config"
    ) as config_mock, patch(
        "integrations.ehal_live.get_ha_adapter", return_value=adapter
    ), patch(
        "integrations.ehal_live.loxone_client.map_huawei_modbus_values",
        return_value=(1.5, 0.0, 0),
    ):
        config_mock.get.side_effect = _config_side_effect("ha")
        ehal_live.write_ess_limits_from_huawei(1, 1.5)

    assert len(captured) == 2
    openems_sp, ha_sp = captured
    assert openems_sp["set_ess_charge_power_limit"] == ha_sp["set_ess_charge_power_limit"]
    assert (
        openems_sp["set_ess_discharge_power_limit"]
        == ha_sp["set_ess_discharge_power_limit"]
    )
    assert openems_sp["set_ess_charge_power_limit"] == 1500.0


def test_loxone_ess_write_uses_non_network_path():
    """Loxone Live writes stay on loxone_client; façade ESS helper requires network backend."""
    ehal_live.reset_adapter_cache()
    with patch("integrations.ehal_live.config") as config_mock, patch(
        "integrations.ehal_live.loxone_client.map_huawei_modbus_values",
        return_value=(1.5, 0.0, 0),
    ) as map_mock, patch(
        "integrations.ehal_live.get_loxone_adapter"
    ) as get_loxone:
        config_mock.get.side_effect = _config_side_effect("loxone")
        assert ehal_live.is_ehal_network_backend() is False
        with pytest.raises(ValueError, match="openems or ha"):
            ehal_live.write_ess_limits_from_huawei(1, 1.5)
        map_mock.assert_called_once_with(1, 1.5)
        get_loxone.assert_not_called()


def test_capabilities_validate_for_all_backends():
    ehal_live.reset_adapter_cache()
    adapter = MagicMock()
    adapter.capabilities.return_value = dict(_FIXTURE_CAPABILITIES)

    factories = (
        ("openems", "integrations.ehal_live.get_openems_adapter"),
        ("ha", "integrations.ehal_live.get_ha_adapter"),
        ("loxone", "integrations.ehal_live.get_loxone_adapter"),
    )
    for backend, factory_path in factories:
        ehal_live.reset_adapter_cache()
        with patch("integrations.ehal_live.config") as config_mock, patch(
            factory_path, return_value=adapter
        ):
            config_mock.get.side_effect = _config_side_effect(backend)
            caps = ehal_live.get_adapter().capabilities()
            out = validate_capabilities(caps)
            assert out["supports_ess_write"] is True
            assert out["supports_evcs_current"] is True
            assert out["adapter_id"] == "contract"


@patch("integrations.ehal_live.config")
def test_is_ehal_network_backend_for_ha(config_mock):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = _config_side_effect("ha")
    assert ehal_live.is_ha_backend() is True
    assert ehal_live.is_ehal_network_backend() is True
    assert ehal_live.is_openems_backend() is False


@patch("integrations.ehal_live.config")
def test_loxone_backend_is_not_network_backend(config_mock):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = _config_side_effect("loxone")
    assert ehal_live.is_loxone_backend() is True
    assert ehal_live.is_ehal_network_backend() is False
    assert ehal_live.is_ha_backend() is False
    assert ehal_live.is_openems_backend() is False
