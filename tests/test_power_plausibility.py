"""Plausibility bounds for pushed power values (HA testbed F21)."""
from __future__ import annotations

import pytest

from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.ha_adapter_core import HaHttpError
from integrations.power_plausibility import (
    ImplausiblePowerError,
    battery_reference_kw,
    check_power_w,
    inverter_pv_reference_kw,
    pv_system_reference_kw,
)
from runtime_store import loxone_push_inbox as inbox


def test_check_accepts_values_within_the_bound():
    check_power_w("inv.wr.sens_inv_power_pv", 12_000.0, 10.0, what="x")  # 1.2 x
    check_power_w("inv.wr.sens_inv_power_pv", 29_999.0, 10.0, what="x")  # < 3 x


def test_check_rejects_kw_sent_as_w_with_a_helpful_message():
    with pytest.raises(ImplausiblePowerError) as exc:
        check_power_w("inv.wr.sens_inv_power_pv", 900_000.0, 10.0, what="the PV system's kWp")
    message = str(exc.value)
    assert "inv.wr.sens_inv_power_pv" in message
    assert "900000 W" in message
    assert "kW sent as W" in message


def test_check_uses_magnitude_and_skips_without_reference():
    with pytest.raises(ImplausiblePowerError):
        check_power_w("ess.house.sens_ess_power", -900_000.0, 5.0, what="x")
    check_power_w("ess.house.sens_ess_power", 900_000.0, None, what="x")


def test_references_come_from_the_configuration():
    inverter = {"id": "wr", "max_ac_power_kw": 8.0, "max_pv_input_kw": 12.0}
    pv = [{"id": "p1", "inverter_id": "wr", "kwp": 10.0}, {"id": "p2", "inverter_id": "x", "kwp": 99.0}]
    assert inverter_pv_reference_kw(inverter, pv) == 12.0
    assert inverter_pv_reference_kw({"id": "wr"}, pv) == 10.0
    assert inverter_pv_reference_kw({"id": "wr"}, []) is None
    assert pv_system_reference_kw({"id": "p", "kwp": 7.5}) == 7.5
    assert pv_system_reference_kw({"id": "p"}) is None
    assert battery_reference_kw(
        {"battery_max_charge_power_kw": 5.0, "battery_max_discharge_power_kw": 6.0}
    ) == 6.0


@pytest.fixture(autouse=True)
def _reset_inbox():
    inbox.reset_memory_for_tests()
    yield
    inbox.reset_memory_for_tests()


def _adapter(monkeypatch: pytest.MonkeyPatch, components: dict, table: dict[str, float]) -> HaAdapter:
    house = {"plant": {"ehal_bindings": {"sens_grid_power_active": ""}}, "profiles": {}}
    monkeypatch.setattr("integrations.pv_attribution.load_house_for_attribution", lambda: house)
    monkeypatch.setattr(
        "integrations.pv_attribution.load_components_for_attribution", lambda: components
    )

    def _fake_read(qid: str, **_kw):
        if qid in table:
            return table[qid], inbox.STATE_OK
        return None, inbox.STATE_READ_ERROR

    monkeypatch.setattr("integrations.ha_push_read.read_push_value", _fake_read)
    qids = {name: name for name in ("sens_grid_power_active", *table) if name != "x"}
    qids["sens_grid_power_active"] = "grid.meter.sens_grid_power_active"
    cfg = HaConfig(
        base_url="http://ha:8123",
        token="t",
        adapter_id="test",
        entities={key: "" for key in qids},
        push_read_qids=qids,
    )
    return HaAdapter(cfg)


def _pv_components() -> dict:
    return {
        "batteries": [],
        "inverters": [
            {"id": "wr", "ac_connection": "grid_tied", "efficiency": 0.97,
             "ehal_bindings": {"inv.wr.sens_inv_power_pv": ""}}
        ],
        "pv_systems": [{"id": "roof", "inverter_id": "wr", "kwp": 10.0, "ehal_bindings": {}}],
    }


def test_adapter_rejects_pv_pushed_in_the_wrong_unit(monkeypatch: pytest.MonkeyPatch):
    adapter = _adapter(
        monkeypatch,
        _pv_components(),
        {"grid.meter.sens_grid_power_active": -874.0, "inv.wr.sens_inv_power_pv": 900_000.0},
    )
    with pytest.raises(HaHttpError, match="Implausible value for inv.wr.sens_inv_power_pv"):
        adapter.read_telemetry()


def test_adapter_accepts_plausible_pv(monkeypatch: pytest.MonkeyPatch):
    adapter = _adapter(
        monkeypatch,
        _pv_components(),
        {"grid.meter.sens_grid_power_active": -874.0, "inv.wr.sens_inv_power_pv": 900.0},
    )
    telemetry = adapter.read_telemetry()
    assert telemetry["sens_grid_power_active"] == pytest.approx(-874.0)


def test_adapter_rejects_ess_power_pushed_in_the_wrong_unit(monkeypatch: pytest.MonkeyPatch):
    components = {
        "batteries": [
            {"id": "house", "type": "house", "inverter_id": "wr",
             "battery_max_charge_power_kw": 5.0, "battery_max_discharge_power_kw": 5.0,
             "ehal_bindings": {"ess.house.sens_ess_power": ""}}
        ],
        "inverters": [{"id": "wr", "ac_connection": "grid_tied", "efficiency": 0.97,
                       "ehal_bindings": {}}],
        "pv_systems": [],
    }
    adapter = _adapter(
        monkeypatch,
        components,
        {"grid.meter.sens_grid_power_active": 100.0, "ess.house.sens_ess_power": 1_474_000.0},
    )
    with pytest.raises(HaHttpError, match="Implausible value for ess.house.sens_ess_power"):
        adapter.read_telemetry()
