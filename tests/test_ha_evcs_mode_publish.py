"""HA backend: the live cycle publishes ``set_evcs_mode`` next to the EV current (bench B4).

Only the EV current used to go out. "Sofort laden" (immediate charge) therefore wrote 0 A and
stopped the charge the user asked for, while the Loxone path sends mode ``now`` and no current.
Setpoints stay numbers for 2.7 (§ 3g): the mode is published as off=0 / pv=1 / now=2.
"""
from __future__ import annotations

import pytest

from ehal import EHAL_SCHEMA_VERSION
from integrations import ehal_live
from integrations.ehal_write import load_published
from integrations.ha_adapter import HaAdapter, HaConfig

CURRENT_QID = "evcs.e_auto.set_evcs_max_current"
MODE_QID = "evcs.e_auto.set_evcs_mode"

EV = {
    "id": "e_auto",
    "name": "E-Auto",
    "type": "ev",
    "nominal_power_kw": 11.0,
    "min_power_kw": 1.4,
    "max_power_kw": 11.0,
}


def _adapter(*, mode_activated: bool, chargers: tuple[str, ...] = ("e_auto",)) -> HaAdapter:
    # Multi-EV M2: charger keys per EV, ``evcs.<Kennung>.<kind>`` (aggregate_ha_entities).
    entities: dict[str, str] = {}
    qids: dict[str, str] = {}
    for charger in chargers:
        kinds = ["set_evcs_max_current"] + (["set_evcs_mode"] if mode_activated else [])
        for kind in kinds:
            qid = f"evcs.{charger}.{kind}"
            entities[qid] = ""
            qids[qid] = qid
    return HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="test",
            entities=entities,
            setpoint_qids=qids,
        )
    )


@pytest.fixture
def ha_cycle(monkeypatch: pytest.MonkeyPatch):
    def install(*, mode_activated: bool = True) -> HaAdapter:
        adapter = _adapter(mode_activated=mode_activated)
        monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
        monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
        monkeypatch.setattr(ehal_live, "live_ev_consumers", lambda: [dict(EV)])
        return adapter

    return install


def test_adapter_publishes_the_mode_as_a_number(ha_cycle) -> None:
    adapter = ha_cycle()
    for name, code in (("off", 0.0), ("pv", 1.0), ("now", 2.0)):
        error = adapter.write_evcs_setpoints(
            "e_auto",
            {
                "schema_version": EHAL_SCHEMA_VERSION,
                "ts": "2026-01-01T00:00:00Z",
                "adapter_id": "test",
                "set_evcs_mode": name,
            },
            voltage_v=230.0,
            phases=1,
        )
        assert error is None
        assert load_published()[MODE_QID] == code


def test_charging_plan_publishes_current_and_mode_now(ha_cycle) -> None:
    ha_cycle()
    error, rows = ehal_live.write_evcs_max_current_from_consumers(
        {"e_auto": 5.0}, {"e_auto": {"active": True, "plugged_in": True}}, {"e_auto": 0}
    )
    assert error is None
    published = load_published()
    assert published[CURRENT_QID] > 0
    assert published[MODE_QID] == 2.0
    assert {row["field"] for row in rows} >= {CURRENT_QID, MODE_QID}


def test_pv_follow_publishes_mode_pv(ha_cycle) -> None:
    ha_cycle()
    ehal_live.write_evcs_max_current_from_consumers(
        {"e_auto": 5.0}, {"e_auto": {"active": True, "plugged_in": True}}, {"e_auto": 1}
    )
    assert load_published()[MODE_QID] == 1.0


def test_no_charging_publishes_mode_off_and_zero_amps(ha_cycle) -> None:
    ha_cycle()
    ehal_live.write_evcs_max_current_from_consumers(
        {"e_auto": 0.0}, {"e_auto": {"active": True, "plugged_in": True}}, {"e_auto": 0}
    )
    published = load_published()
    assert published[CURRENT_QID] == 0.0
    assert published[MODE_QID] == 0.0


def test_immediate_charge_publishes_mode_now_and_no_current(ha_cycle) -> None:
    ha_cycle()
    ctx = {"e_auto": {"active": False, "immediate_charge": True, "skip_loxone_output": True}}
    error, rows = ehal_live.write_evcs_max_current_from_consumers({"e_auto": 0.0}, ctx, {})
    assert error is None
    published = load_published()
    assert published[MODE_QID] == 2.0
    assert CURRENT_QID not in published  # a 0 A here would stop the requested charge
    assert [row["field"] for row in rows] == [MODE_QID]


def test_mode_is_not_published_when_not_activated(ha_cycle) -> None:
    ha_cycle(mode_activated=False)
    ehal_live.write_evcs_max_current_from_consumers(
        {"e_auto": 5.0}, {"e_auto": {"active": True, "plugged_in": True}}, {"e_auto": 0}
    )
    published = load_published()
    assert CURRENT_QID in published
    assert MODE_QID not in published


def test_two_evs_each_write_their_own_charger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-EV M2: one write per EV ↔ wallbox pair, with the pair's own voltage / phases."""
    adapter = _adapter(mode_activated=True, chargers=("auto_a", "auto_b"))
    three_phase = dict(EV, id="auto_b", charging_schedule={
        "nominal_power_voltage_v": 230.0, "nominal_power_phases": 3,
    })
    one_phase = dict(EV, id="auto_a", charging_schedule={
        "nominal_power_voltage_v": 230.0, "nominal_power_phases": 1,
    })
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
    monkeypatch.setattr(ehal_live, "live_ev_consumers", lambda: [one_phase, three_phase])
    plugged = {"active": True, "plugged_in": True}
    error, rows = ehal_live.write_evcs_max_current_from_consumers(
        {"auto_a": 2.3, "auto_b": 6.9}, {"auto_a": plugged, "auto_b": plugged}, {}
    )
    assert error is None
    published = load_published()
    assert published["evcs.auto_a.set_evcs_max_current"] == pytest.approx(10.0)
    assert published["evcs.auto_b.set_evcs_max_current"] == pytest.approx(10.0)
    assert {row["field"] for row in rows} == {
        "evcs.auto_a.set_evcs_max_current",
        "evcs.auto_a.set_evcs_mode",
        "evcs.auto_b.set_evcs_max_current",
        "evcs.auto_b.set_evcs_mode",
    }
