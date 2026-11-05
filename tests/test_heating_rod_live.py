"""SUSI P1 follow-up — Live control of the heating rod: bindings, gate, caps, writes."""
from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import patch

import pytest

from house_config.heat_source import heat_source_efficiency
from house_config.heating_rod_bindings import (
    ROD_BINDINGS_KEY,
    missing_live_signals,
    normalize_rod_bindings,
    rewrite_rod_bindings_slug,
    rod_binding_entity,
    rod_field,
)
from house_config.planning_flex_bridge import collect_planning_flex_consumers
from settings.ehal_marker_resolve import (
    marker_flex_enable,
    marker_flex_power,
    marker_sens_consumer_active,
)

_CID = "wp_heating"
_ROD_ID = "wp_heating_heating_rod"
_ENABLE = f"heatpump.{_ROD_ID}.set_enable"
_POWER = f"heatpump.{_ROD_ID}.sens_power_act"
_ACTIVE = f"heatpump.{_ROD_ID}.sens_consumer_active"
_STORE_TEMP = f"heatpump.{_CID}.sens_temperature_heat_storage"
_STORAGE = {
    "volume_liters": 500.0,
    "heat_loss_kw_per_k": 0.002,
    "setpoint_c": 50.0,
    "tolerance_c": 5.0,
}
_ROD = {"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}


def _consumer(heat_source: dict, *, rod_bindings: dict | None = None, **extra) -> dict:
    consumer = {
        "id": _CID,
        "label": "Heizung",
        "type": "thermal_annual",
        "nominal_power_kw": 1.6,
        "living_area_m2": 0.0,
        "building_class": 2,
        "heat_source": heat_source,
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "heat_storage": _STORAGE,
        "parts": [_ROD],
        "ehal_bindings": {_STORE_TEMP: "T_Speicher"},
        **extra,
    }
    if rod_bindings is not None:
        consumer[ROD_BINDINGS_KEY] = rod_bindings
    return consumer


def _profile(consumer: dict) -> dict:
    return {
        "id": "home",
        "latitude": 47.4,
        "longitude": 9.7,
        "annual_kwh": 9000.0,
        "consumers": [consumer],
    }


_BOUND = {_ENABLE: "Rod_En", _POWER: "Rod_P"}
_GAS = {"type": "gas"}
_HP = {"type": "heat_pump", "heat_pump_type": "luft"}


# --- bindings ---------------------------------------------------------------------------


def test_rod_keys_use_the_heatpump_namespace_and_composite_kennung():
    assert rod_field(_CID, "set_enable") == _ENABLE


def test_normalize_rejects_a_foreign_key():
    with pytest.raises(ValueError, match="unbekanntes Feld 'heatpump.wp_heating.set_enable'"):
        normalize_rod_bindings(
            {"heatpump.wp_heating.set_enable": "x"}, consumer_id=_CID, label="t"
        )


def test_rod_enable_never_becomes_the_parents_release():
    """Regression guard: why the map is not part of ``ehal_bindings``."""
    parent = _consumer(_HP, rod_bindings=_BOUND)
    assert marker_flex_enable(parent) == ""
    assert marker_flex_power(parent) == ""


def test_normalized_consumer_keeps_the_map_and_the_parents_bindings():
    from house_config.profiles_consumers import _copy_rod_bindings

    spec = {"id": _CID, "type": "thermal_annual"}
    _copy_rod_bindings({ROD_BINDINGS_KEY: _BOUND}, spec, profile_id="home")
    assert spec[ROD_BINDINGS_KEY] == _BOUND
    assert "ehal_bindings" not in spec


def test_map_on_another_consumer_type_fails_loud():
    from house_config.profiles_consumers import _copy_rod_bindings

    with pytest.raises(ValueError, match="gehört an den Haus-Wärme-Verbraucher"):
        _copy_rod_bindings(
            {ROD_BINDINGS_KEY: _BOUND}, {"id": "wm", "type": "generic"}, profile_id="home"
        )


def test_serialize_keeps_the_map():
    from house_config.profiles_consumers import _attach_ehal_entity_fields

    out: dict = {}
    _attach_ehal_entity_fields(out, _consumer(_HP, rod_bindings=_BOUND))
    assert out[ROD_BINDINGS_KEY] == _BOUND


def test_planning_entry_carries_only_the_rods_bindings():
    flex = collect_planning_flex_consumers(_profile(_consumer(_HP, rod_bindings=_BOUND)))
    parent, rod = flex
    assert _ENABLE not in (parent.get("ehal_bindings") or {})
    assert rod["ehal_bindings"] == _BOUND
    assert marker_flex_enable(rod) == "Rod_En"
    assert marker_flex_power(rod) == "Rod_P"


def test_empty_address_is_an_activation_flag_with_the_qualified_id():
    rod = rod_binding_entity(_consumer(_GAS, rod_bindings={_ENABLE: ""}))
    assert marker_flex_enable(rod) == _ENABLE


def test_rename_of_the_parent_rewrites_the_rod_kennung():
    assert rewrite_rod_bindings_slug({_ENABLE: "Rod_En"}, new_consumer_id="heizung") == {
        "heatpump.heizung_heating_rod.set_enable": "Rod_En"
    }


def test_push_sources_list_the_rod_signals():
    from ehal.push_signals import _binding_entries

    house = {"profiles": {"home": _profile(_consumer(_GAS, rod_bindings=_BOUND))}}
    entries = _binding_entries(house, {})
    assert ("consumer", _ROD_ID, "heating_rod", _POWER, "Rod_P") in entries
    assert all(entry[1] != _CID or "_heating_rod." not in entry[3] for entry in entries)


def _raw_house(**consumer_fields) -> tuple[dict, dict]:
    consumer = {"id": _CID, "type": "thermal_annual", "heating_system_id": "sys", **consumer_fields}
    components = {
        "heating_systems": [
            {
                "id": "sys",
                "heat_source": _GAS,
                "heating_power_kw": 10.0,
                "heat_storage": _STORAGE,
                "parts": [_ROD],
            }
        ]
    }
    return {"profiles": {"home": {"id": "home", "consumers": [consumer]}}}, components


def test_signal_catalog_offers_the_rod_as_optional_and_activation_writes_its_map():
    from ehal.signal_catalog import iter_catalog_entries, set_binding_activation

    house, components = _raw_house()
    rows = [e for e in iter_catalog_entries(house, components) if e.entity_id == _ROD_ID]
    assert {row.binding_key for row in rows} == {_ENABLE, _POWER, _ACTIVE}
    assert not any(row.is_required for row in rows)

    out, _ = set_binding_activation(
        house,
        components,
        component_kind="consumer",
        entity_id=_ROD_ID,
        binding_key=_ENABLE,
        activated=True,
        consumer_type="heating_rod",
    )
    consumer = out["profiles"]["home"]["consumers"][0]
    assert consumer[ROD_BINDINGS_KEY] == {_ENABLE: ""}
    assert "ehal_bindings" not in consumer


def test_mapping_page_lists_the_rod_and_saves_into_its_map():
    from ui.ehal_loxone_mapping import build_entity_rows
    from ui.ehal_loxone_mapping_persist import apply_entity_bindings

    house, components = _raw_house()
    rows = build_entity_rows(house, "home", components_doc=components)
    row = next(item for item in rows if item["id"] == _ROD_ID)
    assert _ENABLE in row["fields"]

    out = apply_entity_bindings(
        house, profile_id="home", entity_id=_ROD_ID, bindings={_ENABLE: "Rod_En"}
    )
    consumer = out["profiles"]["home"]["consumers"][0]
    assert consumer[ROD_BINDINGS_KEY] == {_ENABLE: "Rod_En"}
    assert "ehal_bindings" not in consumer


# --- gate -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rod_bindings, store_bound, missing",
    [
        ({_ENABLE: "E", _POWER: "P"}, True, []),
        ({_ENABLE: "E", _ACTIVE: "A"}, True, []),
        ({_POWER: "P"}, True, ["set_enable"]),
        ({_ENABLE: "E"}, True, ["sens_power_act oder sens_consumer_active"]),
        ({_ENABLE: "E", _POWER: "P"}, False, ["sens_temperature_heat_storage"]),
    ],
)
def test_missing_live_signals(rod_bindings, store_bound, missing):
    rod = {"id": _ROD_ID, "ehal_bindings": rod_bindings}
    parent = _consumer(_GAS)
    if not store_bound:
        parent["ehal_bindings"] = {}
    assert missing_live_signals(rod, parent) == missing


