"""Startup safe push uses the live ESS limits like the cycle (no HK fallback)."""
from __future__ import annotations

import logging

import pytest

from integrations import ehal_live

_BAT = {
    "id": "house",
    "limits_from_live": True,
    "max_charge_power_kw": 5.0,
    "max_discharge_power_kw": 5.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "control": "full",
}
_LIVE = {
    "ess.house.get_ess_max_charge_power": 3000.0,
    "ess.house.get_ess_max_discharge_power": 0.0,
}


class _Adapter:
    def __init__(self, telemetry: dict | None = None, exc: Exception | None = None):
        self._telemetry = telemetry
        self._exc = exc

    def read_telemetry(self) -> dict:
        if self._exc is not None:
            raise self._exc
        return dict(self._telemetry or {})


@pytest.fixture
def loxone(monkeypatch):
    calls: dict[str, list] = {"huawei": [], "flex": []}
    monkeypatch.setattr(ehal_live.config, "get_battery_params", lambda: dict(_BAT))
    monkeypatch.setattr(
        ehal_live,
        "write_huawei_modbus_states",
        lambda *a, **kw: calls["huawei"].append((a, kw)) or [],
    )
    monkeypatch.setattr(
        ehal_live,
        "write_flexible_consumer_states",
        lambda *a, **kw: calls["flex"].append(a) or [],
    )
    monkeypatch.setattr(ehal_live, "write_inv_ac_limits_from_plan", lambda **kw: (None, []))
    return calls


def _live_reads(monkeypatch, entity: dict, adapter: _Adapter) -> None:
    def enrich(telemetry):
        out = dict(telemetry or {})
        out.update(entity)
        return out

    monkeypatch.setattr(ehal_live, "enrich_telemetry_with_ess_live_limits", enrich)
    monkeypatch.setattr(ehal_live, "get_adapter", lambda: adapter)


def test_loxone_startup_push_sends_the_live_limits(monkeypatch, loxone) -> None:
    _live_reads(monkeypatch, _LIVE, _Adapter(exc=AssertionError("not needed")))
    ehal_live._push_safe_setpoints_loxone()
    (args, kwargs), = loxone["huawei"]
    assert args == (0, 0.0, 99.0)
    params = kwargs["battery_params"]
    assert params["max_discharge_power_kw"] == 0.0
    assert params["max_charge_power_kw"] == 3.0


def test_loxone_startup_push_reads_plant_flat_limits(monkeypatch, loxone) -> None:
    flat = {"get_ess_max_charge_power": 4000.0, "get_ess_max_discharge_power": 1000.0}
    _live_reads(monkeypatch, {}, _Adapter(telemetry=flat))
    ehal_live._push_safe_setpoints_loxone()
    (_args, kwargs), = loxone["huawei"]
    assert kwargs["battery_params"]["max_charge_power_kw"] == 4.0
    assert kwargs["battery_params"]["max_discharge_power_kw"] == 1.0


def test_loxone_startup_push_without_live_limits_is_an_error(
    monkeypatch, loxone, caplog
) -> None:
    _live_reads(
        monkeypatch,
        {"ess.house.get_ess_max_charge_power": 3000.0},
        _Adapter(telemetry={}),
    )
    with caplog.at_level(logging.ERROR, logger=ehal_live.logger.name):
        ehal_live._push_safe_setpoints_loxone()
    assert loxone["huawei"] == []
    assert len(loxone["flex"]) == 1
    messages = [rec.getMessage() for rec in caplog.records]
    assert any(
        "ESS-Sollwerte an Loxone nicht gesendet" in m
        and "get_ess_max_discharge_power" in m
        for m in messages
    )
    assert any("teilweise fehlgeschlagen" in m for m in messages)


def test_loxone_startup_push_unreadable_telemetry_is_an_error(
    monkeypatch, loxone, caplog
) -> None:
    _live_reads(monkeypatch, {}, _Adapter(exc=RuntimeError("inbox empty")))
    with caplog.at_level(logging.ERROR, logger=ehal_live.logger.name):
        ehal_live._push_safe_setpoints_loxone()
    assert loxone["huawei"] == []
    assert any("inbox empty" in rec.getMessage() for rec in caplog.records)


@pytest.fixture
def network(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ehal_live.config, "get_battery_params", lambda: dict(_BAT))
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    monkeypatch.setattr(
        ehal_live,
        "write_ess_setpoints_from_control",
        lambda *a, **kw: calls.append((a, kw)) or (None, []),
    )
    monkeypatch.setattr(
        ehal_live, "write_evcs_max_current_from_consumers", lambda *a: (None, [])
    )
    monkeypatch.setattr(ehal_live, "write_inv_ac_limits_from_plan", lambda **kw: (None, []))
    return calls


def test_network_startup_push_passes_the_live_telemetry(monkeypatch, network) -> None:
    _live_reads(monkeypatch, _LIVE, _Adapter(exc=AssertionError("not needed")))
    ehal_live._push_safe_setpoints_network()
    (args, kwargs), = network
    assert args == (0, 0.0)
    assert kwargs["telemetry"]["ess.house.get_ess_max_discharge_power"] == 0.0


def test_network_startup_push_without_live_limits_is_an_error(
    monkeypatch, network, caplog
) -> None:
    _live_reads(monkeypatch, {}, _Adapter(telemetry={}))
    with caplog.at_level(logging.ERROR, logger=ehal_live.logger.name):
        ehal_live._push_safe_setpoints_network()
    assert network == []
    assert any(
        "ESS-Sollwerte an HA nicht gesendet" in rec.getMessage() for rec in caplog.records
    )
