"""Reserve-refill ping-pong: SoC reading tolerance at the virtual floor, Automatik discharge cap.

Live pattern (2026-11-03, maintainer's plant): floor 12.3 % (min_soc 5 % + 1.1 kWh virtual
reserves). In Automatik the plant covered a 2.3 kW SwimSpa from the battery, fell to 9 %,
and the next cycle refilled from the grid; at a reading of 12 % the MILP forced a 0.21 kW
charge every slot to restore 12.3 %.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from optimizer.powerstation_reserve import (
    SOC_READING_RESOLUTION_PCT,
    prepare_battery_params_for_reserves,
    relax_reserve_floor_for_soc_reading,
    reserve_floor_discharge_cap_kw,
)

_CAP_KWH = 15.0
_ETA = 0.94
_FLOOR = 5.0 + 1.1 / _CAP_KWH * 100.0  # 12.333 %


def _battery() -> dict:
    return {
        "id": "house",
        "battery_capacity_kwh": _CAP_KWH,
        "min_soc": 5.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "max_power_kw": 5.0,
        "efficiency": _ETA,
        "control": "full",
    }


def _reserves() -> list[dict]:
    return [
        {"backing": "virtual", "protected_kwh": 1.0, "asap_charge_kwh": 0.0},
        {"backing": "virtual", "protected_kwh": 0.1, "asap_charge_kwh": 0.0},
    ]


def test_floor_without_soc_is_the_raised_min_soc() -> None:
    battery = prepare_battery_params_for_reserves(_battery(), _reserves())
    assert battery["min_soc"] == pytest.approx(_FLOOR)


@pytest.mark.parametrize(
    ("soc", "expected_min_soc"),
    [
        (12.0, 12.0),  # one reading step below: relaxed to the reading
        (_FLOOR - SOC_READING_RESOLUTION_PCT, _FLOOR - SOC_READING_RESOLUTION_PCT),
        (11.0, _FLOOR),  # more than a step below: the reserve must be refilled
        (13.0, _FLOOR),  # above the floor: unchanged
    ],
)
def test_floor_relaxed_only_within_one_reading_step(soc: float, expected_min_soc: float) -> None:
    battery = prepare_battery_params_for_reserves(_battery(), _reserves(), current_soc=soc)
    assert battery["min_soc"] == pytest.approx(expected_min_soc)


def test_relaxation_never_goes_below_the_configured_min_soc() -> None:
    small = [{"backing": "virtual", "protected_kwh": 0.03, "asap_charge_kwh": 0.0}]  # +0.2 %
    battery = prepare_battery_params_for_reserves(_battery(), small, current_soc=4.6)
    assert battery["min_soc"] == pytest.approx(5.2)


def test_without_virtual_floor_nothing_changes() -> None:
    battery = _battery()
    assert relax_reserve_floor_for_soc_reading(battery, 4.5) == battery
    assert reserve_floor_discharge_cap_kw(battery, 50.0, dt_h=0.25) is None


def test_list_params_relax_the_primary_only() -> None:
    other = {**_battery(), "id": "second", "min_soc": 20.0}
    out = prepare_battery_params_for_reserves([_battery(), other], _reserves(), current_soc=12.0)
    assert out[0]["min_soc"] == pytest.approx(12.0)
    assert out[1]["min_soc"] == pytest.approx(20.0)


def test_discharge_cap_is_the_energy_above_the_floor_per_slot() -> None:
    battery = prepare_battery_params_for_reserves(_battery(), _reserves(), current_soc=13.0)
    cap = reserve_floor_discharge_cap_kw(battery, 13.0, dt_h=0.25)
    expected = (13.0 - _FLOOR) / 100.0 * _CAP_KWH * _ETA / 0.25
    assert cap == pytest.approx(expected)
    assert cap == pytest.approx(0.376, abs=1e-3)


def test_discharge_cap_is_zero_at_a_relaxed_floor_and_large_far_above() -> None:
    at_floor = prepare_battery_params_for_reserves(_battery(), _reserves(), current_soc=12.0)
    assert reserve_floor_discharge_cap_kw(at_floor, 12.0, dt_h=0.25) == pytest.approx(0.0)
    high = prepare_battery_params_for_reserves(_battery(), _reserves(), current_soc=50.0)
    assert reserve_floor_discharge_cap_kw(high, 50.0, dt_h=0.25) > 5.0


def test_discharge_cap_fails_loud_without_efficiency() -> None:
    battery = prepare_battery_params_for_reserves(_battery(), _reserves())
    del battery["efficiency"]
    with pytest.raises(ValueError, match="efficiency"):
        reserve_floor_discharge_cap_kw(battery, 13.0, dt_h=0.25)


@pytest.mark.parametrize(
    ("mode", "expected_discharge"),
    [(0, 0.4), (2, 0.0), (3, 5.0)],
)
def test_map_ess_setpoints_caps_discharge_in_automatik_only(mode: int, expected_discharge: float) -> None:
    from integrations.loxone_writes import map_ess_setpoints

    _active, _charge, discharge, _cmd = map_ess_setpoints(
        mode, 1.0, 5.0, 5.0, automatik_discharge_cap_kw=0.4
    )
    assert discharge == pytest.approx(expected_discharge)


def test_map_ess_setpoints_without_cap_keeps_the_hardware_limit() -> None:
    from integrations.loxone_writes import map_ess_setpoints

    assert map_ess_setpoints(0, 0.0, 5.0, 5.0)[2] == pytest.approx(5.0)


def _flat_matrix() -> list[dict]:
    tz = ZoneInfo("Europe/Vienna")
    start = datetime(2026, 11, 3, 10, 0, tzinfo=tz)
    rows = []
    for i in range(16):
        dt = start + timedelta(minutes=15 * i)
        rows.append(
            {
                "hour": dt.hour,
                "date": dt.date(),
                "slot_datetime": dt,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.4,
                "k_act": 45.0,
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    return rows


def _milp_mode(battery: dict, soc: float) -> tuple[int, float]:
    from optimizer.milp import milp_optimizer

    mode, target_power, *_rest = milp_optimizer(
        _flat_matrix(),
        current_hour=10,
        current_soc=soc,
        battery_params=battery,
        consumers=[],
    )
    return int(mode), float(target_power or 0.0)


def test_milp_reading_one_step_below_the_floor_forces_no_charge() -> None:
    """At a reading of 12 % under a 12.3 % floor the plan holds instead of force-charging."""
    unrelaxed = prepare_battery_params_for_reserves(_battery(), _reserves())
    mode, power = _milp_mode(unrelaxed, 12.0)
    assert mode == 1 and power > 0.0, "precondition: the hard floor forces a slot-0 charge"

    relaxed = prepare_battery_params_for_reserves(_battery(), _reserves(), current_soc=12.0)
    mode, _power = _milp_mode(relaxed, 12.0)
    assert mode != 1


def test_milp_far_below_the_floor_still_refills() -> None:
    battery = prepare_battery_params_for_reserves(_battery(), _reserves(), current_soc=9.0)
    mode, power = _milp_mode(battery, 9.0)
    assert mode == 1 and power > 0.0
