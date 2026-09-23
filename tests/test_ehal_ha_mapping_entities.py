"""UI-adjacent tests for HA entity-centric EHAL mapping (2.6.h)."""
from __future__ import annotations

from integrations.ehal_debug_mapping import (
    expand_ha_telemetry_for_live,
    expand_ha_writes_for_live,
    ha_pattern_b_live_mapping,
)
from integrations.ha_adapter import TELEMETRY_ENERGY_OPTIONAL
from ui.ehal_ha_mapping import _ha_entity_fields
from ui.ehal_loxone_mapping import (
    PLANT_ENTITY_ID,
    apply_entity_bindings,
    build_entity_rows,
    resolve_field_select_default,
)
from ui.loxone_debug import build_ehal_write_rows, build_telemetry_rows


def _sample_house() -> dict:
    return {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "sensor.grid",
                "sens_pv_production_active": "sensor.pv",
                "sens_ess_soc": "sensor.soc",
            }
        },
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "wallbox",
                        "label": "Wallbox",
                        "type": "ev",
                        "ehal_bindings": {
                            "sens_evcs_active_power": "sensor.ev_power",
                            "set_evcs_max_current": "number.ev_amps",
                        },
                    }
                ],
            }
        },
    }


def test_ha_plant_fields_include_energy_optional():
    rows = build_entity_rows(_sample_house(), "live")
    plant = next(r for r in rows if r["id"] == PLANT_ENTITY_ID)
    fields = _ha_entity_fields(plant)
    for name in TELEMETRY_ENERGY_OPTIONAL:
        assert name in fields


def test_ha_apply_entity_bindings_per_entity():
    house = _sample_house()
    house = apply_entity_bindings(
        house,
        profile_id="live",
        entity_id=PLANT_ENTITY_ID,
        bindings={
            "sens_grid_power_active": "sensor.grid2",
            "sens_pv_production_active": "sensor.pv",
            "sens_ess_soc": "sensor.soc",
            "sens_pv_energy": "sensor.pv_energy",
        },
    )
    assert house["plant"]["ehal_bindings"]["sens_grid_power_active"] == "sensor.grid2"
    assert house["plant"]["ehal_bindings"]["sens_pv_energy"] == "sensor.pv_energy"
    # EV consumer untouched
    ev = house["profiles"]["live"]["consumers"][0]["ehal_bindings"]
    assert ev["sens_evcs_active_power"] == "sensor.ev_power"

    house = apply_entity_bindings(
        house,
        profile_id="live",
        entity_id="wallbox",
        bindings={
            "sens_evcs_active_power": "sensor.ev_power_b",
            "set_evcs_max_current": "number.ev_amps",
        },
    )
    ev = house["profiles"]["live"]["consumers"][0]["ehal_bindings"]
    assert ev["sens_evcs_active_power"] == "sensor.ev_power_b"
    assert house["plant"]["ehal_bindings"]["sens_grid_power_active"] == "sensor.grid2"


def test_ha_empty_only_select_default():
    assert (
        resolve_field_select_default("sensor.keep", "sensor.propose") == "sensor.keep"
    )
    assert resolve_field_select_default("", "sensor.propose") == "sensor.propose"


def test_ha_pattern_b_live_mapping_entity_centric():
    house = _sample_house()
    mapping = ha_pattern_b_live_mapping(house)
    assert mapping["sens_ess_soc"] == "sensor.soc"
    assert mapping["wallbox:sens_evcs_active_power"] == "sensor.ev_power"
    assert mapping["wallbox:set_evcs_max_current"] == "number.ev_amps"
    assert "sens_evcs_active_power" not in mapping


def test_expand_ha_telemetry_aliases_ev_to_consumer():
    house = _sample_house()
    expanded = expand_ha_telemetry_for_live(
        {
            "sens_ess_soc": 55.0,
            "sens_evcs_active_power": 3200.0,
            "schema_version": 3,
        },
        house,
    )
    assert expanded["sens_ess_soc"] == 55.0
    assert expanded["wallbox:sens_evcs_active_power"] == 3200.0
    assert "sens_evcs_active_power" not in expanded


def test_expand_ha_writes_and_live_rows():
    house = _sample_house()
    writes = expand_ha_writes_for_live(
        [
            {
                "field": "set_evcs_max_current",
                "value": 16,
                "success": True,
                "written_at": "t0",
                "message": "",
            }
        ],
        house,
    )
    assert writes[0]["field"] == "wallbox:set_evcs_max_current"
    mapping = ha_pattern_b_live_mapping(house)
    rows = build_ehal_write_rows(
        writes,
        mapping=mapping,
        expected_fields=["set_ess_mode", "wallbox:set_evcs_max_current"],
    )
    by_field = {r["EHAL-Feld"]: r for r in rows}
    assert by_field["wallbox:set_evcs_max_current"]["Mapping"] == "number.ev_amps"
    assert by_field["wallbox:set_evcs_max_current"]["Erfolg"] == "Ja"


def test_ha_telemetry_rows_entity_centric_mapping_column():
    house = _sample_house()
    mapping = ha_pattern_b_live_mapping(house)
    telemetry = expand_ha_telemetry_for_live(
        {"sens_ess_soc": 40.0, "sens_evcs_active_power": 100.0},
        house,
    )
    rows = build_telemetry_rows(
        telemetry,
        "t1",
        mapping=mapping,
        expected_fields=["sens_ess_soc", "wallbox:sens_evcs_active_power"],
    )
    by_field = {r["EHAL-Feld"]: r for r in rows}
    assert by_field["sens_ess_soc"]["Mapping"] == "sensor.soc"
    assert by_field["sens_ess_soc"]["Wert"] == "40.0"
    assert by_field["wallbox:sens_evcs_active_power"]["Mapping"] == "sensor.ev_power"
    assert by_field["wallbox:sens_evcs_active_power"]["Wert"] == "100.0"
