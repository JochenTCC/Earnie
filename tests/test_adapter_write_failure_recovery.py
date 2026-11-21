"""A failed setpoint write must not disable control for the process lifetime.

The daemon caches its adapters (``integrations.ehal_live_adapters``). Before this fix a
single failed ESS write flipped ``_supports_ess_write`` / ``_supports_ess_active`` and a
single failed charger write put the charger into ``_evcs_disabled``; every later cycle then
skipped those writes quietly until the daemon restarted. Now every cycle tries again, and
each failure is reported as a write_error (and logged), never as a quiet skip.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from ehal import EHAL_SCHEMA_VERSION
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.loxone_adapter import LoxoneAdapter, LoxoneConfig
from integrations.loxone_comm_trace import LoxoneWriteRecord
from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig
from runtime_store import loxone_push_inbox as inbox

_TS = "2026-11-18T12:00:00Z"


def _ess(adapter_id: str, **fields) -> dict:
    return {"schema_version": EHAL_SCHEMA_VERSION, "ts": _TS, "adapter_id": adapter_id, **fields}


def _evcs(adapter_id: str, amps: float) -> dict:
    return _ess(adapter_id, set_evcs_max_current=amps)


@pytest.fixture(autouse=True)
def _reset_inbox():
    inbox.reset_memory_for_tests()
    yield
    inbox.reset_memory_for_tests()


# --- OpenEMS -------------------------------------------------------------------------


def _openems(**kwargs) -> OpenemsAdapter:
    return OpenemsAdapter(
        OpenemsConfig(
            base_url="http://edge:8084",
            username="x",
            password="admin",
            adapter_id="openems-lab",
            **kwargs,
        )
    )


def _ok(*_args, **_kwargs):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"value": None}
    return response


@patch("integrations.openems_adapter.requests.post")
def test_openems_timeout_on_active_power_is_retried_next_cycle(post_mock):
    import requests

    post_mock.side_effect = [requests.Timeout("read timed out"), _ok(), _ok()]
    adapter = _openems()
    doc = _ess(
        "openems-lab",
        set_ess_active_power=-2000.0,
        set_ess_charge_power_limit=3000.0,
    )

    error = adapter.write_setpoints(doc)
    assert error is not None
    assert error["failed_fields"] == ["set_ess_active_power"]
    assert error["retryable"] is True
    assert adapter.capabilities()["supports_ess_write"] is True

    post_mock.reset_mock(side_effect=True)
    post_mock.side_effect = _ok
    assert adapter.write_setpoints(doc) is None
    urls = [call.args[0] for call in post_mock.call_args_list]
    assert any("SetActivePowerEquals" in url for url in urls)
    assert any("SetActivePowerGreaterOrEquals" in url for url in urls)
    assert adapter.last_write_error() is None


@patch("integrations.openems_adapter.requests.post")
def test_openems_failed_charger_is_retried_next_cycle(post_mock):
    response = MagicMock()
    response.status_code = 503
    post_mock.return_value = response
    adapter = _openems(evcs_channels=(("auto_a", "evcs0", "SetChargePowerLimit"),))

    error = adapter.write_evcs_setpoints("auto_a", _evcs("openems-lab", 10), voltage_v=230, phases=1)
    assert error is not None and error["failed_fields"] == ["set_evcs_max_current"]

    post_mock.reset_mock(return_value=True)
    post_mock.side_effect = _ok
    assert (
        adapter.write_evcs_setpoints("auto_a", _evcs("openems-lab", 10), voltage_v=230, phases=1)
        is None
    )
    assert adapter.last_skipped_fields() == []
    assert len(post_mock.call_args_list) == 1


@patch("integrations.openems_adapter.requests.post")
def test_openems_persistent_lock_is_reported_every_cycle(post_mock):
    response = MagicMock()
    response.status_code = 403
    post_mock.return_value = response
    adapter = _openems()
    doc = _ess("openems-lab", set_ess_charge_power_limit=500)
    for _cycle in range(3):
        error = adapter.write_setpoints(doc)
        assert error is not None and error["hub_status"] == "403"
    assert post_mock.call_count == 3


# --- Home Assistant ------------------------------------------------------------------


_HA_ENTITIES = {
    "set_ess_active_power": "",
    "set_ess_charge_power_limit": "",
    "set_ess_discharge_power_limit": "",
    "set_ess_mode": "",
}
_HA_FORCE = {"driver": "huawei_solar", "device_id": "dev-1", "duration_min": 20}


def _ha(setpoint_qids: dict[str, str], entities: dict[str, str] | None = None) -> HaAdapter:
    return HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="test",
            entities=dict(entities if entities is not None else _HA_ENTITIES),
            ha_ess_force=_HA_FORCE,
            setpoint_qids=setpoint_qids,
        )
    )


def test_ha_missing_binding_does_not_block_the_force_release(caplog):
    """L18: the 0 W release must go out even when another ESS field cannot be published."""
    from integrations.ehal_write import clear_published_for_tests, load_published

    clear_published_for_tests()
    adapter = _ha(
        {
            "set_ess_active_power": "ess.house.set_ess_active_power",
            # charge limit binding missing -> "Missing HA push setpoint binding"
            "set_ess_discharge_power_limit": "ess.house.set_ess_discharge_power_limit",
            "set_ess_mode": "ess.house.set_ess_mode",
        }
    )
    caps_before = adapter.capabilities()
    assert caps_before["supports_ess_write"] is True

    force = _ess(
        "test",
        set_ess_active_power=-2000.0,
        set_ess_charge_power_limit=3000.0,
        set_ess_discharge_power_limit=3000.0,
        set_ess_mode=1,
    )
    with caplog.at_level(logging.WARNING, logger="integrations.ha_adapter"):
        error = adapter.write_setpoints(force)
    assert error is not None
    assert error["failed_fields"] == ["set_ess_charge_power_limit"]
    assert "Missing HA push setpoint binding" in error["message"]
    assert any("HA setpoint publish failed" in r.getMessage() for r in caplog.records)
    assert load_published()["ess.house.set_ess_active_power"] == pytest.approx(-2000.0)
    # One call only: ``ts`` is the call time and may tick between two calls.
    caps_after = adapter.capabilities()
    assert {k: v for k, v in caps_after.items() if k != "ts"} == {
        k: v for k, v in caps_before.items() if k != "ts"
    }

    release = _ess(
        "test",
        set_ess_active_power=0.0,
        set_ess_charge_power_limit=3000.0,
        set_ess_discharge_power_limit=3000.0,
        set_ess_mode=0,
    )
    error = adapter.write_setpoints(release)
    assert error is not None and error["failed_fields"] == ["set_ess_charge_power_limit"]
    published = load_published()
    assert published["ess.house.set_ess_active_power"] == pytest.approx(0.0)
    assert published["ess.house.set_ess_mode"] == pytest.approx(0.0)
    # Reported as a failure, not as an unconfigured (silent) field.
    assert "set_ess_charge_power_limit" not in adapter.last_unconfigured_fields()


def test_ha_failed_publish_is_retried_next_cycle(monkeypatch):
    from integrations.ehal_write import clear_published_for_tests, load_published

    clear_published_for_tests()
    qids = {key: f"ess.house.{key}" for key in _HA_ENTITIES}
    adapter = _ha(qids)
    real = adapter._try_setpoint_write
    calls = {"n": 0}

    def flaky(field_name, value):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, None, f"EHAL publish rejected for {field_name}"
        return real(field_name, value)

    monkeypatch.setattr(adapter, "_try_setpoint_write", flaky)
    doc = _ess("test", set_ess_active_power=-1500.0, set_ess_mode=1)
    assert adapter.write_setpoints(doc) is not None
    assert adapter.write_setpoints(doc) is None
    assert load_published()["ess.house.set_ess_active_power"] == pytest.approx(-1500.0)
    assert adapter.last_unconfigured_fields() == []


def test_ha_failed_charger_is_retried_next_cycle(monkeypatch):
    from integrations.ehal_write import clear_published_for_tests, load_published

    clear_published_for_tests()
    qid = "evcs.e_auto.set_evcs_max_current"
    adapter = _ha({qid: qid}, entities={qid: ""})
    real = adapter._try_setpoint_write
    calls = {"n": 0}

    def flaky(field_name, value):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, None, f"EHAL publish rejected for {field_name}"
        return real(field_name, value)

    monkeypatch.setattr(adapter, "_try_setpoint_write", flaky)
    error = adapter.write_evcs_setpoints("e_auto", _evcs("test", 10), voltage_v=230, phases=3)
    assert error is not None and error["failed_fields"] == ["set_evcs_max_current"]
    assert adapter.write_evcs_setpoints("e_auto", _evcs("test", 12), voltage_v=230, phases=3) is None
    assert load_published()[qid] == pytest.approx(12.0)
    assert adapter.last_skipped_fields() == []


# --- Loxone --------------------------------------------------------------------------


def _loxone(**kwargs) -> LoxoneAdapter:
    return LoxoneAdapter(
        LoxoneConfig(
            adapter_id="loxone-home",
            charge_power_name="Charge",
            discharge_power_name="Discharge",
            active_power_name="Active",
            control_cmd_name="Cmd",
            **kwargs,
        )
    )


def _flaky_publish(fail_first: int):
    calls = {"n": 0}

    def publish(qid, value, *, io_name=""):
        calls["n"] += 1
        return LoxoneWriteRecord(io_name or qid, float(value), calls["n"] > fail_first, "t")

    return publish


def test_loxone_failed_ess_write_is_retried_next_cycle():
    adapter = _loxone()
    doc = _ess("loxone-home", set_ess_active_power=-1000.0, set_ess_charge_power_limit=2000.0)
    with patch(
        "integrations.loxone_writes._publish_setpoint_traced",
        side_effect=_flaky_publish(fail_first=1),
    ) as pub:
        error = adapter.write_setpoints(doc)
        assert error is not None and error["failed_fields"] == ["set_ess_active_power"]
        assert adapter.capabilities()["supports_ess_write"] is True
        pub.reset_mock()
        assert adapter.write_setpoints(doc) is None
        written = {call.args[0] for call in pub.call_args_list}
    assert any(qid.endswith("set_ess_active_power") for qid in written)
    assert any(qid.endswith("set_ess_charge_power_limit") for qid in written)
    assert adapter.last_skipped_fields() == []


def test_loxone_failed_charger_is_retried_next_cycle():
    adapter = _loxone(evcs_markers=(("e_auto", "EV_A", ""),))
    with patch(
        "integrations.loxone_writes._publish_setpoint_traced",
        side_effect=_flaky_publish(fail_first=1),
    ) as pub:
        error = adapter.write_evcs_setpoints(
            "e_auto", _evcs("loxone-home", 16), voltage_v=230, phases=1
        )
        assert error is not None and error["failed_fields"] == ["set_evcs_max_current"]
        pub.reset_mock()
        assert (
            adapter.write_evcs_setpoints("e_auto", _evcs("loxone-home", 16), voltage_v=230, phases=1)
            is None
        )
        assert [call.args[0] for call in pub.call_args_list] == [
            "evcs.e_auto.set_evcs_max_current"
        ]
    assert adapter.last_skipped_fields() == []
