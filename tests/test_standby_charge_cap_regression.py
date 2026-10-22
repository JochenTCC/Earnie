"""Regression: Delta 3 standby refill must never exceed HK ∩ live charge power.

Symptom (dump ``debug_dump_20261015_222809``, fixed 2026-10-21, prod-verified 2026-10-22):
Chart1 SoC of the standby powerstation jumped steeply in a cheap slot (~1.5 kW per
quarter hour) above the Hauskonfigurator / Smarthome max-charge ceiling, because
``collect_standby_packs`` used the raw HK charge power and skipped the 2.7.j effective
limits.

``test_powerstation_2_7_h.py`` pins the collected ``max_charge_power_kw``. These tests
follow the cap through planning: cheap-slot refill -> house load -> Chart1 SoC.
Synthetic numbers only (no customer data).
"""
from __future__ import annotations

import pytest

from house_config.powerstation import ROLE_STANDBY_BACKUP
from optimizer.powerstation_standby import (
    SOURCE_GRID,
    advance_physical_standby_soc_after_slot,
    apply_standby_load_relief,
    collect_standby_packs,
    live_source_and_charge,
    plan_standby_horizon,
)

_PS_ID = "ecoflow_delta_3"
_DT_H = 0.25
_CAPACITY_KWH = 1.024
_EFFICIENCY = 0.95


def _powerstation(*, hk_charge_kw: float) -> dict:
    return {
        "id": _PS_ID,
        "type": "powerstation",
        "backing": "physical",
        "role": ROLE_STANDBY_BACKUP,
        "attached_consumer_ids": ["dev-pc"],
        "battery_capacity_kwh": _CAPACITY_KWH,
        "battery_max_charge_power_kw": hk_charge_kw,
        "battery_max_discharge_power_kw": 2.2,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "limits_from_live": True,
    }


def _cheap_slots_then_expensive() -> list[dict]:
    """One cheap slot (the refill window), then expensive ones (island).

    A single cheap slot forces the refill into that slot, so the charge power sits
    on the cap instead of being spread over equal-price slots.
    """
    cheap = {"k_act": 0.05, "expected_p_act": 1.0, "expected_p_pv": 0.0}
    dear = {"k_act": 0.40, "expected_p_act": 1.0, "expected_p_pv": 0.0}
    return [dict(cheap)] + [dict(dear) for _ in range(7)]


def _plan(*, hk_charge_kw: float, live_charge_w: float | None):
    telemetry = (
        None
        if live_charge_w is None
        else {f"ess.{_PS_ID}.get_ess_max_charge_power": live_charge_w}
    )
    packs = collect_standby_packs(
        powerstations=[_powerstation(hk_charge_kw=hk_charge_kw)],
        appliances=[{"id": "dev-pc", "default_power_kw": 0.1}],
        telemetry=telemetry,
    )
    matrix = _cheap_slots_then_expensive()
    plans = plan_standby_horizon(
        matrix, packs, current_soc_by_id={_PS_ID: 10.0}, dt_h=_DT_H
    )
    return packs, matrix, plans


@pytest.mark.parametrize(
    ("hk_charge_kw", "live_charge_w", "expected_cap_kw"),
    [
        (1.5, 1000.0, 1.0),  # live below HK -> live wins
        (1.0, 1500.0, 1.0),  # live above HK -> live never loosens HK
        (1.0, None, 1.0),  # no live telemetry -> HK
    ],
)
def test_cheap_slot_refill_stays_within_hk_and_live_cap(
    hk_charge_kw, live_charge_w, expected_cap_kw
):
    packs, matrix, plans = _plan(hk_charge_kw=hk_charge_kw, live_charge_w=live_charge_w)

    assert packs[0]["max_charge_power_kw"] == pytest.approx(expected_cap_kw)
    charge_kw = plans[_PS_ID]["charge_kw"]
    assert max(charge_kw) > 0.0, "scenario must actually refill in the cheap slots"
    assert max(charge_kw) <= expected_cap_kw + 1e-6

    # The house MILP sees the refill as extra grid load: never more than the cap.
    relieved = apply_standby_load_relief(matrix, plans)
    for before, after, source in zip(
        matrix, relieved, plans[_PS_ID]["source_select"], strict=True
    ):
        if source == SOURCE_GRID:
            assert after["expected_p_act"] - before["expected_p_act"] <= expected_cap_kw + 1e-6

    # The slot that is written to the device respects the cap too.
    _sources, charges = live_source_and_charge(plans, slot=0)
    assert charges[_PS_ID] <= expected_cap_kw + 1e-6


def test_chart1_soc_rise_per_slot_respects_cap():
    """Chart1 SoC must not climb faster than cap x efficiency per slot."""
    packs, _matrix, plans = _plan(hk_charge_kw=1.5, live_charge_w=1000.0)
    packs_by_id = {p["powerstation_id"]: p for p in packs}
    soc = {_PS_ID: 10.0}
    max_rise_pct = 1.0 * _EFFICIENCY * _DT_H / _CAPACITY_KWH * 100.0

    for slot in range(len(plans[_PS_ID]["source_select"])):
        before = soc[_PS_ID]
        advance_physical_standby_soc_after_slot(
            soc, plans=plans, packs_by_id=packs_by_id, slot_index=slot, dt_h=_DT_H
        )
        assert soc[_PS_ID] - before <= max_rise_pct + 1e-6
