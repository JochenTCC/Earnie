"""Fail-safe values per written signal in the HA carrier package (follow-up of issue #60)."""
from __future__ import annotations

import copy

import jinja2
import pytest
import yaml

from house_config.ha_fail_safe import (
    house_with_fail_safe_values,
    normalize_ha_fail_safe_values,
)
from house_config.profiles_store import (
    load_house_profiles_document,
    save_house_profiles_document,
)
from integrations.ha_carrier_yaml import (
    build_carrier_yaml,
    fail_safe_signals_from_docs,
)

_DISCHARGE = "ess.house.set_ess_discharge_power_limit"
_CHARGE = "ess.house.set_ess_charge_power_limit"
_ACTIVE = "ess.house.set_ess_active_power"
_MODE = "ess.house.set_ess_mode"
_CURRENT = "evcs.e_auto.set_evcs_max_current"
_WATCHDOG = "earnie_watchdog_release_force"


def _house(values: dict | None = None, **plant) -> dict:
    out = {"plant": {"ehal_bindings": {"sens_grid_power_active": ""}, **plant}, "profiles": {}}
    if values is not None:
        out["plant"]["ha_fail_safe_values"] = values
    return out


def _components(*fields: str) -> dict:
    return {
        "batteries": [
            {
                "id": "house",
                "type": "house",
                "ehal_bindings": {field: "" for field in (fields or (_DISCHARGE, _CHARGE, _ACTIVE))},
            }
        ]
    }


def _build(house: dict, components: dict | None = None, **kwargs) -> str:
    return build_carrier_yaml(
        house,
        components or _components(),
        earnie_host="earnie-ha-lab",
        earnie_port=8541,
        token="TEST_TOKEN_12345678",
        repeat_s=10.0,
        **kwargs,
    )


def _watchdog(text: str) -> dict:
    found = [a for a in yaml.safe_load(text)["automation"] if a["id"] == _WATCHDOG]
    assert len(found) == 1
    return found[0]


def _writes(auto: dict) -> dict[str, dict]:
    """Fail-safe write per entity: its variables step and its action."""
    actions = auto["actions"]
    out = {}
    for variables, branch in zip(actions, actions[1:]):
        if "variables" in variables and "if" in branch:
            action = branch["else"][0]
            out[action["target"]["entity_id"]] = {"vars": variables["variables"], "action": action, "if": branch}
    return out


def _render(template: str, **context) -> str:
    env = jinja2.Environment()
    env.filters["is_number"] = lambda v: isinstance(v, (int, float))
    env.filters["float"] = float
    return env.from_string(template).render(none=None, **context)


# --- What the watchdog writes


def test_no_value_keeps_the_package_byte_identical():
    assert _build(_house()) == _build(_house({}))
    auto = _watchdog(_build(_house()))
    assert not _writes(auto)
    assert "release forced power" in auto["alias"]


def test_discharge_limit_is_written_when_earnie_is_unreachable():
    auto = _watchdog(_build(_house({_DISCHARGE: 5000})))

    write = _writes(auto)["ENTITY_ess_house_set_ess_discharge_power_limit"]
    assert write["vars"]["ehal_raw"] == 5000.0
    assert write["action"]["continue_on_error"] is True
    assert write["action"]["data"]["value"] == "{{ hub_value }}"
    assert write["action"]["action"].endswith(".set_value")
    assert auto["triggers"][0]["to"] == ["unavailable", "unknown"]
    assert "fail-safe" in auto["alias"]
    assert "fail-safe values written" in auto["actions"][-1]["data"]["message"]


def test_a_signal_without_a_value_stays_untouched():
    auto = _watchdog(_build(_house({_DISCHARGE: 5000})))

    assert set(_writes(auto)) == {"ENTITY_ess_house_set_ess_discharge_power_limit"}
    assert "charge_power_limit" not in str(auto["actions"]).replace("discharge_power_limit", "")


def test_active_power_is_still_released_next_to_a_limit():
    auto = _watchdog(_build(_house({_DISCHARGE: 5000})))

    release = auto["actions"][0]
    assert release["target"]["entity_id"] == "ENTITY_ess_house_set_ess_active_power"
    assert release["data"]["value"] == 0


def test_a_value_for_the_active_power_replaces_the_release_to_zero():
    auto = _watchdog(_build(_house({_ACTIVE: -1500})))

    assert all(action.get("data", {}).get("value") != 0 for action in auto["actions"])
    assert _writes(auto)["ENTITY_ess_house_set_ess_active_power"]["vars"]["ehal_raw"] == -1500.0


def test_watchdog_exists_for_a_value_even_without_active_power():
    """The reported case: a discharge lock on a plant without forced power."""
    plain = _build(_house(), _components(_DISCHARGE))
    assert _WATCHDOG not in plain

    auto = _watchdog(_build(_house({_DISCHARGE: 5000}), _components(_DISCHARGE)))

    assert set(_writes(auto)) == {"ENTITY_ess_house_set_ess_discharge_power_limit"}
    assert auto["actions"][0] == {"variables": auto["actions"][0]["variables"]}


def test_vendor_force_stops_and_writes_the_limits():
    force = {"driver": "huawei_solar", "device_id": "dev-luna-1"}
    auto = _watchdog(_build(_house({_DISCHARGE: 5000}, ha_ess_force=force)))

    assert auto["actions"][0]["action"] == "huawei_solar.stop_forcible_charge"
    assert set(_writes(auto)) == {"ENTITY_ess_house_set_ess_discharge_power_limit"}


def test_header_names_the_values_and_says_when_they_are_not_applied():
    assert f"fail-safe values of: {_DISCHARGE}" in _build(_house({_DISCHARGE: 5000}))

    off = _build(_house({_DISCHARGE: 5000}), watchdog_s=0)

    assert _WATCHDOG not in off
    assert f"Fail-safe values are not applied, no watchdog: {_DISCHARGE}" in off


# --- Unit conversion in the generated template


@pytest.mark.parametrize(
    "entity_unit,expected",
    [("w", 5000.0), ("watt", 5000.0), ("kw", 5.0), ("mw", 0.005)],
)
def test_power_value_is_converted_to_the_entity_unit(entity_unit, expected):
    write = _writes(_watchdog(_build(_house({_DISCHARGE: 5000}))))[
        "ENTITY_ess_house_set_ess_discharge_power_limit"
    ]

    rendered = _render(write["vars"]["hub_value"], ehal_raw=write["vars"]["ehal_raw"], entity_unit=entity_unit)

    assert float(rendered) == pytest.approx(expected)


def test_unknown_unit_is_logged_and_not_written():
    write = _writes(_watchdog(_build(_house({_DISCHARGE: 5000}))))[
        "ENTITY_ess_house_set_ess_discharge_power_limit"
    ]

    rendered = _render(write["vars"]["hub_value"], ehal_raw=5000.0, entity_unit="kwh")

    assert rendered == "None"
    assert write["if"]["if"][0]["value_template"] == "{{ hub_value is none }}"
    message = write["if"]["then"][0]["data"]["message"]
    assert _DISCHARGE in message and "need W" in message


def test_setpoint_automations_keep_their_conversion():
    """The template moved into a helper; the setpoint path must render the same."""
    doc = yaml.safe_load(_build(_house()))
    auto = next(a for a in doc["automation"] if a["id"] == "earnie_setpoint_ess_house_set_ess_active_power")
    variables = auto["actions"][0]["variables"]
    assert variables["ehal_raw"] == "{{ state_attr('sensor.earnie_ehal_status', 'ess.house.set_ess_active_power') }}"
    assert float(_render(variables["hub_value"], ehal_raw=2000.0, entity_unit="kw")) == pytest.approx(2.0)


# --- Which signals can take a value


def test_signals_with_a_unit_are_offered_modes_are_not():
    components = _components(_DISCHARGE, _ACTIVE, _MODE, "ess.house.set_ess_source_select")

    ids = [sig.ehal_id for sig in fail_safe_signals_from_docs(_house(), components)]

    assert ids == [_DISCHARGE, _ACTIVE]


def test_active_power_is_not_offered_with_a_vendor_force():
    force = {"driver": "huawei_solar", "device_id": "dev-luna-1"}

    ids = [sig.ehal_id for sig in fail_safe_signals_from_docs(_house(ha_ess_force=force), _components())]

    assert _ACTIVE not in ids and _DISCHARGE in ids


@pytest.mark.parametrize(
    "values,components,plant",
    [
        pytest.param({"ess.gone.set_ess_active_power": 0}, None, {}, id="signal-not-activated"),
        pytest.param({_MODE: 1}, _components(_MODE, _ACTIVE), {}, id="mode-has-no-unit"),
        pytest.param(
            {_ACTIVE: 0},
            None,
            {"ha_ess_force": {"driver": "huawei_solar", "device_id": "dev-luna-1"}},
            id="active-power-with-vendor-force",
        ),
    ],
)
def test_a_value_the_package_cannot_apply_fails_the_generation(values, components, plant):
    with pytest.raises(ValueError, match="Fail-safe-Wert ohne passendes Signal"):
        _build(_house(values, **plant), components)


# --- Stored values


@pytest.mark.parametrize("raw", [None, {}])
def test_absent_or_empty_values_normalize_to_none(raw):
    assert normalize_ha_fail_safe_values(raw) is None


def test_values_normalize_to_floats_and_zero_is_a_value():
    assert normalize_ha_fail_safe_values({_DISCHARGE: 5000, _CHARGE: 0}) == {_DISCHARGE: 5000.0, _CHARGE: 0.0}
    assert normalize_ha_fail_safe_values({_ACTIVE: -1500}) == {_ACTIVE: -1500.0}


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param([1], id="not-an-object"),
        pytest.param({_DISCHARGE: "5000"}, id="text"),
        pytest.param({_DISCHARGE: True}, id="bool"),
        pytest.param({_DISCHARGE: None}, id="none"),
        pytest.param({_DISCHARGE: float("nan")}, id="nan"),
        pytest.param({_DISCHARGE: float("inf")}, id="inf"),
        pytest.param({_DISCHARGE: -1}, id="negative-limit"),
        pytest.param({_CURRENT: -6}, id="negative-current"),
        pytest.param({"ess.house.sens_ess_soc": 1}, id="read-signal"),
    ],
)
def test_invalid_values_are_rejected(raw):
    with pytest.raises(ValueError, match="plant.ha_fail_safe_values"):
        normalize_ha_fail_safe_values(raw)


def test_house_with_values_replaces_all_and_keeps_the_rest_of_the_plant():
    house = _house({_CHARGE: 1000.0}, max_export_power_kw=5.0)
    original = copy.deepcopy(house)

    out = house_with_fail_safe_values(house, {_DISCHARGE: 5000.0, _ACTIVE: None})

    assert out["plant"]["ha_fail_safe_values"] == {_DISCHARGE: 5000.0}
    assert out["plant"]["max_export_power_kw"] == 5.0
    assert house == original


def test_house_with_no_values_drops_the_key():
    out = house_with_fail_safe_values(_house({_CHARGE: 1000.0}), {_CHARGE: None})

    assert "ha_fail_safe_values" not in out["plant"]


def test_values_survive_the_profile_store_round_trip(tmp_path):
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {**_house({_DISCHARGE: 5000}), "profiles": []})

    doc = load_house_profiles_document(str(path))

    assert doc["plant"]["ha_fail_safe_values"] == {_DISCHARGE: 5000.0}


def test_a_file_without_values_loads_without_the_key(tmp_path):
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {**_house(), "profiles": []})

    assert "ha_fail_safe_values" not in load_house_profiles_document(str(path))["plant"]
