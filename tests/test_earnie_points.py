"""Earnie-Points calculation, rule version 3 (docs/workflow/earnie-points.md)."""
from __future__ import annotations

import itertools

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


def test_rule_version_is_3():
    assert POINTS_RULE_VERSION == 3


@pytest.mark.parametrize(
    ("kwp", "expected"),
    [(0.0, 0), (3.4, 0), (3.5, 1), (10.4, 1), (10.5, 2), (14.0, 2), (17.5, 3), (20.0, 3)],
)
def test_pv_one_point_per_7_kwp_rounded_half_up(kwp, expected):
    assert _points(_components(kwp=[kwp]))["pv"] == expected


@pytest.mark.parametrize(
    ("kwh", "expected"),
    [(0.0, 0), (1.9, 0), (2.0, 1), (5.9, 1), (6.0, 2), (10.0, 3), (12.0, 3), (14.0, 4), (40.0, 10)],
)
def test_storage_one_point_per_4_kwh_rounded_half_up(kwh, expected):
    assert _points(_components(kwh=[kwh]))["storage"] == expected


@pytest.mark.parametrize("kwp", [0.0, 5.0, 10.0, 30.0])
def test_storage_does_not_depend_on_pv(kwp):
    assert _points(_components(kwp=[kwp], kwh=[10.0]))["storage"] == 3


def test_sums_are_added_before_rounding_and_float_noise_ignored():
    assert _points(_components(kwp=[1.75, 1.75]))["pv"] == 1  # 3.5 kWp, exactly 0.5
    assert _points(_components(kwp=[1.1, 1.2, 1.2]))["pv"] == 1  # 3.5000000000000004
    assert _points(_components(kwh=[1.0, 1.0]))["storage"] == 1  # 2 kWh, exactly 0.5


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


@pytest.mark.parametrize(
    ("kwh", "expected"), [((), 3), ((0.0,), 3), ((5.0,), 3), ((12.0,), 3), ((14.0,), 4), ((40.0,), 10)]
)
def test_storage_counts_at_least_3_with_a_wallbox(kwh, expected):
    one = _points(_components(kwh=kwh), [_ev()])
    assert (one["storage"], one["wallbox"]) == (expected, 2)
    # The floor applies once per plant, not per wallbox.
    two = _points(_components(kwh=kwh), [_ev(), _ev("ev2")])
    assert (two["storage"], two["wallbox"]) == (expected, 4)


def test_no_wallbox_no_storage_floor():
    assert _points(_components(kwh=[0.0]))["storage"] == 0
    assert _points(_components(kwh=[4.0]))["storage"] == 1


def test_first_battery_at_a_wallbox_does_not_lower_the_total():
    """Version 2 lost 4 points here: the battery removed the "without storage" extra."""
    without = _points(_components(kwp=[10.0]), [_ev()])["total"]
    for kwh in (1.0, 5.0, 10.0, 20.0):
        assert _points(_components(kwp=[10.0], kwh=[kwh]), [_ev()])["total"] >= without


def test_bidirectional_car_battery_counts_a_quarter_in_wallbox():
    plant = _components(kwp=[10.0], kwh=[10.0])
    # Car 60 kWh at a quarter = 15 kWh: 15/4 = 3.75 → 4 points on top of the wallbox.
    result = _points(plant, [_ev(bidirectional=True)])
    assert result["storage"] == 3
    assert result["wallbox"] == 2 + 4


def test_bidirectional_gives_at_least_one_point():
    plant = _components(kwp=[10.0], kwh=[2.0])
    # Car 1 kWh at a quarter: 0.25/4 → 0, minimum 1 per bidirectional wallbox.
    small = _ev(bidirectional=True, battery_capacity_kwh=1.0)
    assert _points(plant, [small])["wallbox"] == 2 + 1
    two = [small, _ev("ev2", bidirectional=True, battery_capacity_kwh=1.0)]
    assert _points(plant, two)["wallbox"] == 4 + 2


def test_bidirectional_false_is_a_plain_wallbox():
    assert _points(_components(kwh=[5.0]), [_ev(bidirectional=False)])["wallbox"] == 2


def test_bidirectional_car_battery_does_not_count_towards_the_storage_floor():
    result = _points(_components(), [_ev(bidirectional=True)])
    assert (result["storage"], result["wallbox"]) == (3, 2 + 4)


def test_bidirectional_points_do_not_depend_on_the_stationary_storage():
    """A difference of rounded storage values dropped by a point at 2 kWh (17 kWh → 4, 2 kWh → 1)."""
    for kwh in (0.0, 2.0, 5.0, 14.0):
        assert _points(_components(kwh=[kwh]), [_ev(bidirectional=True)])["wallbox"] == 2 + 4


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
        ("gas", 0.0, 6),
        ("oil", 0.0, 6),
        ("district_heat", 0.0, 6),
        ("gas", 12.5, 6),  # PV does not reduce the rod points any more
        ("pellets", 0.0, 3),
        ("wood", 0.0, 3),
        ("pellets", 25.0, 3),
        ("electric_direct", 0.0, 0),
        ("heat_pump", 0.0, 0),
    ],
)
def test_heating_rod_by_heat_source_independent_of_pv(source, kwp, expected):
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
        "total": 6, "pv": 1, "storage": 3, "wallbox": 2, "heat": 0, "heating_rod": 0, "other": 0
    }
    assert _points(_components(kwp=[10.0], kwh=[10.0]), [_heating()]) == {
        "total": 5, "pv": 1, "storage": 3, "wallbox": 0, "heat": 1, "heating_rod": 0, "other": 0
    }
    assert _points(_components(kwp=[12.0, 8.0], kwh=[15.0]), [_ev(), _heating("gas", rod=True)]) == {
        "total": 15, "pv": 3, "storage": 4, "wallbox": 2, "heat": 0, "heating_rod": 6, "other": 0
    }


_GRID_KWP = [0.0, 1.0, 3.4, 3.5, 5.0, 7.0, 10.0, 10.5, 12.5, 15.0, 20.0, 25.0, 30.0]
_GRID_KWH = [0.0, 0.5, 0.9, 1.0, 1.9, 2.0, 4.0, 5.0, 6.0, 9.0, 10.0, 12.0, 14.0, 15.0, 20.0, 30.0]
_GRID_WALLBOXES = [0, 1, 2, 3]
_GRID_HEATING = [None, "heat_pump", "gas", "pellets"]
_KEYS = ("total", "pv", "storage", "wallbox", "heat", "heating_rod", "other")


def _grid_plant(kwp, kwh, wallboxes, bidirectional, heating) -> dict:
    consumers = [_ev(f"ev{i}", bidirectional=i < bidirectional) for i in range(wallboxes)]
    if heating is not None:
        consumers.append(_heating(heating, rod=True))
    return _points(_components(kwp=[kwp], kwh=[kwh]), consumers)


def test_no_upgrade_lowers_the_points():
    """Guarantee of rule version 3: more PV, more storage or another wallbox (plain or
    bidirectional) never lowers the total, nor any single part."""
    plants = {}
    for kwp, kwh, wallboxes, heating in itertools.product(
        _GRID_KWP, _GRID_KWH, _GRID_WALLBOXES, _GRID_HEATING
    ):
        for bidirectional in range(wallboxes + 1):
            key = (kwp, kwh, wallboxes, bidirectional, heating)
            plants[key] = _grid_plant(*key)

    def upgrades(key):
        kwp, kwh, wallboxes, bidirectional, heating = key
        i, j = _GRID_KWP.index(kwp), _GRID_KWH.index(kwh)
        if i + 1 < len(_GRID_KWP):
            yield "pv", (_GRID_KWP[i + 1], kwh, wallboxes, bidirectional, heating)
        if j + 1 < len(_GRID_KWH):
            yield "storage", (kwp, _GRID_KWH[j + 1], wallboxes, bidirectional, heating)
        if wallboxes + 1 in _GRID_WALLBOXES:
            yield "wallbox", (kwp, kwh, wallboxes + 1, bidirectional, heating)
            yield "bidirectional wallbox", (kwp, kwh, wallboxes + 1, bidirectional + 1, heating)

    checked = 0
    for key, before in plants.items():
        for what, upgraded in upgrades(key):
            after = plants[upgraded]
            lower = [k for k in _KEYS if after[k] < before[k]]
            assert not lower, f"{what}: {key} {before} -> {upgraded} {after}"
            checked += 1
    assert checked > 10_000


def test_heating_rod_and_storage_parts_ignore_pv_on_the_grid():
    """Version 2 lowered both parts with more PV (rod deduction, storage kink)."""
    for kwh, wallboxes in itertools.product(_GRID_KWH, (0, 1)):
        parts = {
            (p["storage"], p["heating_rod"], p["wallbox"])
            for p in (_grid_plant(kwp, kwh, wallboxes, 0, "gas") for kwp in _GRID_KWP)
        }
        assert len(parts) == 1


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


def test_dynamic_cars_count_each_allowed_wallbox_once():
    """Dynamic EVs: every wallbox they may use counts once, however many cars share it."""
    dyn = {"wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["box1", "box2"]}}
    points = compute_earnie_points(
        _components(kwh=(10.0,)),
        {"consumers": [_ev("a", **dyn), _ev("b", **dyn), _ev("c")]},
    )
    assert points["wallbox"] == 6


def test_ev_without_wallbox_assignment_raises():
    car = _ev("a")
    del car["wallbox_assignment"]
    with pytest.raises(ValueError, match="wallbox_assignment"):
        compute_earnie_points(_components(), {"consumers": [car]})
