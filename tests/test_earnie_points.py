"""Earnie-Points calculation, rule version 2 (docs/workflow/earnie-points.md)."""
from __future__ import annotations

import pytest

from house_config.earnie_points import POINTS_RULE_VERSION, compute_earnie_points


def _components(kwp=(), kwh=()) -> dict:
    return {
        "pv_systems": [{"id": f"pv{i}", "kwp": v} for i, v in enumerate(kwp)],
        "batteries": [{"id": f"b{i}", "battery_capacity_kwh": v} for i, v in enumerate(kwh)],
    }


def _ev(cid="ev", **extra) -> dict:
    return {
        "id": cid,
        "type": "ev",
        "nominal_power_kw": 11.0,
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {"nominal_power_phases": 3},
        "wallbox_assignment": {"mode": "fixed", "wallbox_id": cid},
        **extra,
    }


def _generic(role="flex", nominal=3.0, **extra) -> dict:
    return {
        "id": "g",
        "type": "generic",
        "nominal_power_kw": nominal,
        "earnie_role": role,
        "schedule": {"runs_per_week": 2, "start_shift_h": 4.0},
        **extra,
    }


def _heating(source="heat_pump", *, rod=False, **extra) -> dict:
    heat_source = {"type": source}
    if source == "heat_pump":
        heat_source["heat_pump_type"] = "luft"
    consumer = {
        "id": "hp",
        "type": "thermal_annual",
        "nominal_power_kw": 3.5,
        "thermal": {"heat_source": heat_source},
        "parts": [],
        **extra,
    }
    if rod:
        consumer["parts"] = [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}]
    return consumer


def _rc(nominal=3.0, **extra) -> dict:
    return {"id": "rc", "type": "thermal_rc", "nominal_power_kw": nominal, **extra}


def _points(components=None, consumers=()) -> dict:
    return compute_earnie_points(components or _components(), {"consumers": list(consumers)})


def test_rule_version_is_2():
    assert POINTS_RULE_VERSION == 2


@pytest.mark.parametrize(
    ("kwp", "expected"),
    [(0.0, 0), (3.4, 0), (3.5, 1), (10.4, 1), (10.5, 2), (14.0, 2), (17.5, 3), (20.0, 3)],
)
def test_pv_one_point_per_7_kwp_rounded_half_up(kwp, expected):
    assert _points(_components(kwp=[kwp]))["pv"] == expected


@pytest.mark.parametrize(
    ("kwp", "kwh", "expected"),
    [
        (10.0, 0.0, 0),
        (10.0, 2.4, 0),  # 0.48
        (10.0, 2.5, 1),  # 0.5 rounds up
        (10.0, 10.0, 2),  # all below the kink: 10/5
        (10.0, 15.0, 4),  # 10/5 + 5/2.5
        (5.0, 10.0, 3),  # 5/5 + 5/2.5
        (0.0, 5.0, 2),  # no PV: everything above the kink, 5/2.5
    ],
)
def test_storage_kink_at_1_kwh_per_kwp(kwp, kwh, expected):
    assert _points(_components(kwp=[kwp], kwh=[kwh]))["storage"] == expected


def test_sums_are_added_before_rounding_and_float_noise_ignored():
    assert _points(_components(kwp=[1.75, 1.75]))["pv"] == 1  # 3.5 kWp, exactly 0.5
    assert _points(_components(kwp=[1.1, 1.2, 1.2]))["pv"] == 1  # 3.5000000000000004
    assert _points(_components(kwp=[10.0], kwh=[1.25, 1.25]))["storage"] == 1


def test_no_pv_no_storage_no_consumers_is_zero():
    assert _points() == {
        "total": 0, "pv": 0, "storage": 0, "wallbox": 0, "heat": 0, "heating_rod": 0, "other": 0
    }


def test_wallbox_two_points_each_regardless_of_phases():
    with_storage = _components(kwh=[5.0])
    assert _points(with_storage, [_ev()])["wallbox"] == 2
    single = _ev(charging_schedule={"nominal_power_phases": 1})
    assert _points(with_storage, [single])["wallbox"] == 2
    assert _points(with_storage, [_ev(), _ev("ev2")])["wallbox"] == 4


@pytest.mark.parametrize(("kwh", "expected"), [(0.0, 6), (0.9, 6), (1.0, 2)])
def test_wallbox_without_storage_adds_4_once(kwh, expected):
    assert _points(_components(kwh=[kwh]), [_ev()])["wallbox"] == expected
    assert _points(_components(kwh=[kwh]), [_ev(), _ev("ev2")])["wallbox"] == expected + 2


def test_no_wallbox_no_storage_extra():
    assert _points(_components(kwh=[0.0]))["wallbox"] == 0


def test_bidirectional_car_battery_counts_a_quarter_in_wallbox():
    plant = _components(kwp=[10.0], kwh=[10.0])
    # 10 + 60/4 = 25 kWh: 10/5 + 15/2.5 = 8 storage points, 6 more than the stationary 2.
    result = _points(plant, [_ev(bidirectional=True)])
    assert result["storage"] == 2
    assert result["wallbox"] == 2 + 6


def test_bidirectional_gives_at_least_one_point():
    plant = _components(kwp=[10.0], kwh=[2.0])
    # Stationary 2 kWh → 0.4 → 0; with the car 2 + 1/4 = 2.25 kWh → 0.45 → 0: delta 0, minimum 1.
    small = _ev(bidirectional=True, battery_capacity_kwh=1.0)
    assert _points(plant, [small])["wallbox"] == 2 + 1
    two = [small, _ev("ev2", bidirectional=True, battery_capacity_kwh=1.0)]
    assert _points(plant, two)["wallbox"] == 4 + 2


def test_bidirectional_false_is_a_plain_wallbox():
    assert _points(_components(kwh=[5.0]), [_ev(bidirectional=False)])["wallbox"] == 2


def test_bidirectional_without_storage_keeps_the_extra():
    # Car battery does not lift the "without storage" extra: 2 + 4 + car (15 kWh above kink → 6).
    assert _points(_components(), [_ev(bidirectional=True)])["wallbox"] == 2 + 4 + 6


def test_bidirectional_without_capacity_raises():
    car = _ev(bidirectional=True)
    del car["battery_capacity_kwh"]
    with pytest.raises(ValueError, match="Wallbox 'ev': battery_capacity_kwh fehlt"):
        _points(consumers=[car])


def test_heat_pump_one_point_boiler_none():
    assert _points(consumers=[_heating()])["heat"] == 1
    for source in ("gas", "oil", "pellets", "wood", "district_heat", "electric_direct"):
        assert _points(consumers=[_heating(source)])["heat"] == 0


@pytest.mark.parametrize(
    ("source", "kwp", "expected"),
    [
        ("gas", 0.0, 7),
        ("oil", 0.0, 7),
        ("district_heat", 0.0, 7),
        ("gas", 10.0, 5),  # 7 - 2
        ("gas", 12.5, 5),  # 7 - 2.5 = 4.5 rounds up
        ("pellets", 0.0, 4),
        ("wood", 0.0, 4),
        ("pellets", 15.0, 1),
        ("pellets", 25.0, 0),  # 4 - 5, at least 0
        ("electric_direct", 0.0, 0),
        ("heat_pump", 0.0, 0),
    ],
)
def test_heating_rod_by_heat_source_minus_pv(source, kwp, expected):
    result = _points(_components(kwp=[kwp]), [_heating(source, rod=True)])
    assert result["heating_rod"] == expected


def test_no_heating_rod_part_no_points():
    assert _points(consumers=[_heating("gas")])["heating_rod"] == 0


def test_heating_without_heat_source_raises():
    broken = _heating("gas")
    broken["thermal"] = {}
    with pytest.raises(ValueError, match="heat_source fehlt"):
        _points(consumers=[broken])


def _cooled(cooling_type: str, *, heating_on: bool) -> dict:
    carrier = {**_heating(), "cooling": {"type": cooling_type}}
    key = "consumers" if heating_on else "inactive_consumers"
    return {"cooling_enabled": True, "consumers": [], "inactive_consumers": [], key: [carrier]}


def test_heat_pump_and_air_conditioner():
    split = compute_earnie_points(_components(), _cooled("split", heating_on=True))
    assert split["heat"] == 2
    # The reversible heat pump is one device: counted once, with or without heating.
    reversible = compute_earnie_points(_components(), _cooled("heat_pump", heating_on=True))
    assert reversible["heat"] == 1
    cooling_only = compute_earnie_points(_components(), _cooled("heat_pump", heating_on=False))
    assert cooling_only["heat"] == 1
    switched_off = {**_cooled("split", heating_on=True), "cooling_enabled": False}
    assert compute_earnie_points(_components(), switched_off)["heat"] == 1


def test_manual_and_known_consumers_never_counted():
    for role in ("manual", "known"):
        result = _points(consumers=[_generic(role=role, nominal=7.0)])
        assert result["total"] == 0


def test_generic_without_schedule_is_known_and_not_counted():
    consumer = {"id": "g", "type": "generic", "nominal_power_kw": 5.0}
    assert _points(consumers=[consumer])["total"] == 0


def test_other_flex_consumers_from_2_5_kw():
    assert _points(consumers=[_generic(nominal=2.4)])["other"] == 0
    assert _points(consumers=[_generic(nominal=2.5)])["other"] == 1
    assert _points(consumers=[_rc(nominal=2.4)])["other"] == 0
    assert _points(consumers=[_rc(nominal=2.5)])["other"] == 1


def test_spec_examples():
    assert _points(_components(kwp=[7.0]), [_ev()]) == {
        "total": 7, "pv": 1, "storage": 0, "wallbox": 6, "heat": 0, "heating_rod": 0, "other": 0
    }
    assert _points(_components(kwp=[10.0], kwh=[10.0]), [_heating()]) == {
        "total": 4, "pv": 1, "storage": 2, "wallbox": 0, "heat": 1, "heating_rod": 0, "other": 0
    }
    assert _points(_components(kwp=[12.0, 8.0], kwh=[15.0]), [_ev(), _heating("gas", rod=True)]) == {
        "total": 11, "pv": 3, "storage": 3, "wallbox": 2, "heat": 0, "heating_rod": 3, "other": 0
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


def test_two_cars_at_one_wallbox_count_one_wallbox():
    """Data model 6: the points count wallboxes, not cars."""
    shared = {"wallbox_assignment": {"mode": "fixed", "wallbox_id": "box"}}
    one = compute_earnie_points(_components(kwh=(10.0,)), {"consumers": [_ev("a", **shared)]})
    two = compute_earnie_points(
        _components(kwh=(10.0,)),
        {"consumers": [_ev("a", **shared), _ev("b", **shared)]},
    )
    assert two["wallbox"] == one["wallbox"]
