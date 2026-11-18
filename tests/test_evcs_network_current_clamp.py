"""Network EVCS write (HA / OpenEMS) uses the same current rule as the Loxone path.

``_write_one_charger`` used to convert the raw planned kW straight to amps: a plan below the
wallbox minimum went out below the minimum (charging stops, the HA number rejects it) and PV
follow sent mode ``pv`` with the current capped at the plan average. The Loxone path clamps
to 0 or [min_power_kw, nominal] and sends P_max with PV follow (``loxone_control_outputs``).
"""
from __future__ import annotations

import pytest

from integrations import ehal_live
from integrations.ehal_write import load_published
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.loxone_writes import flex_consumer_setpoint_amps

CURRENT_QID = "evcs.e_auto.set_evcs_max_current"
MODE_QID = "evcs.e_auto.set_evcs_mode"

# 3 phases at 230 V: 6 A = 4.14 kW minimum, 16 A = 11.04 kW nominal.
EV = {
    "id": "e_auto",
    "name": "E-Auto",
    "type": "ev",
    "charger_id": "e_auto",
    "nominal_power_kw": 11.04,
    "min_power_kw": 4.14,
    "max_power_kw": 11.04,
    "charging_schedule": {"nominal_power_voltage_v": 230.0, "nominal_power_phases": 3},
    "ehal_bindings": {"set_evcs_max_current": "", "set_evcs_mode": ""},
}
PLUGGED = {"e_auto": {"active": True, "plugged_in": True}}


def _adapter() -> HaAdapter:
    qids = {CURRENT_QID: CURRENT_QID, MODE_QID: MODE_QID}
    return HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="test",
            entities={CURRENT_QID: "", MODE_QID: ""},
            setpoint_qids=qids,
        )
    )


@pytest.fixture
def network_cycle(monkeypatch: pytest.MonkeyPatch):
    def install(*, ha: bool = True) -> None:
        adapter = _adapter()
        monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: ha)
        monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
        monkeypatch.setattr(ehal_live, "live_ev_consumers", lambda: [dict(EV)])

    return install


def test_plan_below_minimum_is_raised_to_the_wallbox_minimum(network_cycle) -> None:
    network_cycle()
    error, _rows = ehal_live.write_evcs_max_current_from_consumers(
        {"e_auto": 2.0}, PLUGGED, {"e_auto": 0}
    )
    assert error is None
    published = load_published()
    assert published[CURRENT_QID] == pytest.approx(6.0)
    assert published[MODE_QID] == 2.0  # now


def test_plan_above_nominal_is_capped(network_cycle) -> None:
    network_cycle()
    ehal_live.write_evcs_max_current_from_consumers({"e_auto": 20.0}, PLUGGED, {"e_auto": 0})
    assert load_published()[CURRENT_QID] == pytest.approx(16.0)


def test_pv_follow_sends_p_max_with_mode_pv(network_cycle) -> None:
    network_cycle()
    ehal_live.write_evcs_max_current_from_consumers({"e_auto": 2.0}, PLUGGED, {"e_auto": 1})
    published = load_published()
    assert published[CURRENT_QID] == pytest.approx(16.0)
    assert published[MODE_QID] == 1.0  # pv


def test_pv_follow_without_planned_power_is_off(network_cycle) -> None:
    network_cycle()
    ehal_live.write_evcs_max_current_from_consumers({"e_auto": 0.0}, PLUGGED, {"e_auto": 1})
    published = load_published()
    assert published[CURRENT_QID] == 0.0
    assert published[MODE_QID] == 0.0  # off


@pytest.mark.parametrize(
    "ctx",
    [
        {"active": False, "plugged_in": True},
        {"active": True, "anticipated": True, "plugged_in": False},
    ],
    ids=["inactive", "anticipated-not-plugged"],
)
def test_inactive_or_anticipated_unplugged_writes_zero_and_off(network_cycle, ctx) -> None:
    network_cycle()
    ehal_live.write_evcs_max_current_from_consumers({"e_auto": 7.0}, {"e_auto": ctx}, {"e_auto": 1})
    published = load_published()
    assert published[CURRENT_QID] == 0.0
    assert published[MODE_QID] == 0.0


def test_immediate_charge_is_unchanged(network_cycle) -> None:
    network_cycle()
    ctx = {"e_auto": {"active": False, "immediate_charge": True, "skip_loxone_output": True}}
    error, rows = ehal_live.write_evcs_max_current_from_consumers({"e_auto": 2.0}, ctx, {})
    assert error is None
    published = load_published()
    assert published[MODE_QID] == 2.0
    assert CURRENT_QID not in published
    assert [row["field"] for row in rows] == [MODE_QID]


def test_openems_style_backend_is_clamped_too(network_cycle) -> None:
    network_cycle(ha=False)
    ehal_live.write_evcs_max_current_from_consumers({"e_auto": 2.0}, PLUGGED, {"e_auto": 0})
    published = load_published()
    assert published[CURRENT_QID] == pytest.approx(6.0)
    assert MODE_QID not in published


@pytest.mark.parametrize(
    ("planned_kw", "pv_follow", "ctx"),
    [
        (0.0, 0, PLUGGED["e_auto"]),
        (2.0, 0, PLUGGED["e_auto"]),
        (7.5, 0, PLUGGED["e_auto"]),
        (20.0, 0, PLUGGED["e_auto"]),
        (2.0, 1, PLUGGED["e_auto"]),
        (7.5, 0, {"active": False}),
        (7.5, 0, {"active": True, "anticipated": True, "plugged_in": False}),
    ],
)
def test_network_current_matches_loxone_current(network_cycle, planned_kw, pv_follow, ctx) -> None:
    network_cycle()
    powers = {"e_auto": planned_kw}
    contexts = {"e_auto": ctx}
    pv = {"e_auto": pv_follow}
    ehal_live.write_evcs_max_current_from_consumers(powers, contexts, pv)
    loxone_amps = flex_consumer_setpoint_amps(dict(EV), powers, contexts, pv)
    assert loxone_amps is not None
    assert load_published()[CURRENT_QID] == pytest.approx(loxone_amps)
