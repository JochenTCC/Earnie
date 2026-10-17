"""Earnie-Points calculation (docs/workflow/earnie-points.md)."""
from __future__ import annotations

import pytest

from house_config.earnie_points import compute_earnie_points


def _components(kwp=(), kwh=()) -> dict:
    return {
        "pv_systems": [{"id": f"pv{i}", "kwp": v} for i, v in enumerate(kwp)],
        "batteries": [{"id": f"b{i}", "battery_capacity_kwh": v} for i, v in enumerate(kwh)],
    }


def _ev(phases=None, **extra) -> dict:
    sched: dict = {}
    if phases is not None:
        sched["nominal_power_phases"] = phases
    return {"id": "ev", "type": "ev", "nominal_power_kw": 11.0, "charging_schedule": sched, **extra}


def _generic(role="flex", nominal=3.0, **extra) -> dict:
    return {
        "id": "g",
        "type": "generic",
        "nominal_power_kw": nominal,
        "earnie_role": role,
        "schedule": {"runs_per_week": 2, "start_shift_h": 4.0},
        **extra,
    }


def _heat_pump() -> dict:
    return {"id": "hp", "type": "thermal_annual", "nominal_power_kw": 3.5}


def _rc(nominal=3.0, **extra) -> dict:
    return {"id": "rc", "type": "thermal_rc", "nominal_power_kw": nominal, **extra}


def _points(components=None, consumers=()) -> dict:
    return compute_earnie_points(components or _components(), {"consumers": list(consumers)})


@pytest.mark.parametrize(
    ("kwp", "expected"),
    [(0.0, 0), (0.1, 1), (6.0, 1), (6.1, 2), (10.0, 2), (10.1, 3), (14.0, 3), (14.1, 4), (20.0, 5)],
)
def test_pv_boundaries(kwp, expected):
    assert _points(_components(kwp=[kwp]))["pv"] == expected


@pytest.mark.parametrize(
    ("kwh", "expected"),
    [(0.0, 0), (0.5, 1), (5.0, 1), (5.1, 2), (10.0, 2), (10.1, 3), (15.0, 3), (15.1, 4)],
)
def test_storage_boundaries(kwh, expected):
    assert _points(_components(kwh=[kwh]))["storage"] == expected


def test_sums_are_added_before_tiering_and_float_noise_ignored():
    assert _points(_components(kwp=[3.0, 3.0]))["pv"] == 1
    assert _points(_components(kwp=[3.3, 3.3, 3.4]))["pv"] == 2  # 10.0, not 10.0000000000000002
    assert _points(_components(kwh=[2.5, 2.5, 5.0]))["storage"] == 2


def test_no_pv_no_storage_no_consumers_is_zero():
    assert _points() == {
        "total": 0, "pv": 0, "storage": 0, "wallbox": 0, "heat": 0, "other": 0
    }


def test_wallbox_phases_and_bidirectional():
    assert _points(consumers=[_ev()])["wallbox"] == 1
    assert _points(consumers=[_ev(phases=1)])["wallbox"] == 1
    assert _points(consumers=[_ev(phases=3)])["wallbox"] == 2
    assert _points(consumers=[_ev(phases=3, bidirectional=True)])["wallbox"] == 3
    assert _points(consumers=[_ev(bidirectional=True)])["wallbox"] == 3
    assert _points(consumers=[_ev(bidirectional=False, phases=3)])["wallbox"] == 2


def test_wallbox_phases_from_loxone_fallback():
    ev = _ev()
    ev["charging_schedule"] = {"loxone": {"nominal_power_phases": 3}}
    assert _points(consumers=[ev])["wallbox"] == 2


def test_wallbox_two_phases_raises():
    with pytest.raises(ValueError, match="nominal_power_phases=2"):
        _points(consumers=[_ev(phases=2)])


def test_each_wallbox_counts_not_each_car():
    assert _points(consumers=[_ev(phases=3), {**_ev(phases=1), "id": "ev2"}])["wallbox"] == 3


def test_heat_pump_and_air_conditioner():
    assert _points(consumers=[_heat_pump()])["heat"] == 1
    ac = _generic(nominal=1.2, appliance_kind="air_conditioner")
    assert _points(consumers=[ac])["heat"] == 1
    assert _points(consumers=[_rc(appliance_kind="air_conditioner")])["heat"] == 1
    assert _points(consumers=[_heat_pump(), ac])["heat"] == 2


def test_manual_and_known_consumers_never_counted():
    for role in ("manual", "known"):
        big = _generic(role=role, nominal=7.0)
        ac = _generic(role=role, nominal=2.0, appliance_kind="air_conditioner")
        result = _points(consumers=[big, ac])
        assert result["other"] == 0
        assert result["heat"] == 0
        assert result["total"] == 0


def test_generic_without_schedule_is_known_and_not_counted():
    consumer = {"id": "g", "type": "generic", "nominal_power_kw": 5.0}
    assert _points(consumers=[consumer])["total"] == 0


def test_other_flex_consumers_from_2_5_kw():
    assert _points(consumers=[_generic(nominal=2.4)])["other"] == 0
    assert _points(consumers=[_generic(nominal=2.5)])["other"] == 1
    assert _points(consumers=[_rc(nominal=2.4)])["other"] == 0
    assert _points(consumers=[_rc(nominal=2.5)])["other"] == 1


def test_air_conditioner_not_double_counted_as_other():
    ac = _generic(nominal=5.0, appliance_kind="air_conditioner")
    result = _points(consumers=[ac, _rc(nominal=5.0, appliance_kind="air_conditioner")])
    assert result["heat"] == 2
    assert result["other"] == 0


def test_spec_examples():
    assert _points(_components(kwp=[6.0]), [_ev(phases=1)])["total"] == 2
    assert _points(_components(kwp=[10.0], kwh=[9.0]), [_heat_pump()]) == {
        "total": 5, "pv": 2, "storage": 2, "wallbox": 0, "heat": 1, "other": 0
    }
    assert _points(_components(kwp=[12.0, 8.0], kwh=[10.0, 5.0]), [_ev(phases=3)]) == {
        "total": 10, "pv": 5, "storage": 3, "wallbox": 2, "heat": 0, "other": 0
    }


@pytest.mark.parametrize(
    ("components", "message"),
    [
        ({"pv_systems": [{"id": "a"}]}, "pv_systems 'a': kwp fehlt"),
        ({"pv_systems": [{"id": "a", "kwp": "x"}]}, "kwp ist keine Zahl"),
        ({"pv_systems": [{"id": "a", "kwp": -1}]}, "kwp muss >= 0 sein"),
        ({"batteries": [{"id": "b"}]}, "batteries 'b': battery_capacity_kwh fehlt"),
        ({"pv_systems": "nope"}, "pv_systems muss eine Liste sein"),
    ],
)
def test_invalid_components_raise(components, message):
    with pytest.raises(ValueError, match=message):
        compute_earnie_points(components, {"consumers": []})


def test_invalid_profile_raises():
    with pytest.raises(ValueError, match="profile.consumers muss eine Liste sein"):
        compute_earnie_points(_components(), {})
