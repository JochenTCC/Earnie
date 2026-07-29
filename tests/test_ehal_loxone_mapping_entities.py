"""UI-adjacent tests for entity-centric EHAL Loxone mapping save (2.4.k)."""
from __future__ import annotations

from ui.ehal_loxone_mapping import (
    EV_FIELDS,
    FLEX_FIELDS,
    PLANT_ENTITY_ID,
    PLANT_FIELDS,
    _field_select_caption,
    apply_entity_bindings,
    build_entity_rows,
    fields_for_consumer,
)


def test_fields_for_consumer_ev_vs_flex():
    assert "set_evcs_max_current" in fields_for_consumer({"type": "ev"})
    assert "get_evcs_limit_soc" in EV_FIELDS
    assert "sens_power_consumers" in PLANT_FIELDS
    assert fields_for_consumer({"type": "thermal_annual"}) == FLEX_FIELDS


def test_field_select_caption_includes_ehal_name():
    caption = _field_select_caption("sens_ess_soc", required=True)
    assert "`sens_ess_soc`" in caption
    assert caption.endswith(" *")
    assert "sens_ess_soc" != caption  # meaning text present beside the name


def test_build_entity_rows_includes_plant_and_consumers():
    house = {
        "plant": {"ehal_bindings": {"sens_ess_soc": "SOC"}},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {"id": "ev1", "label": "Auto", "type": "ev"},
                    {"id": "wp", "label": "WP", "type": "thermal_annual"},
                ],
            }
        },
    }
    rows = build_entity_rows(house, "live")
    ids = [r["id"] for r in rows]
    assert ids == [PLANT_ENTITY_ID, "ev1", "wp"]
    assert rows[0]["bindings"]["sens_ess_soc"] == "SOC"
    assert "set_evcs_max_current" in rows[1]["fields"]
    assert "set_evcs_current" not in rows[1]["fields"]
    assert "flex.power_name" in rows[2]["fields"]


def test_apply_entity_bindings_writes_plant_and_consumer():
    house = {
        "plant": {},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [{"id": "ev1", "label": "Auto", "type": "ev"}],
            }
        },
    }
    house = apply_entity_bindings(
        house,
        profile_id="live",
        entity_id=PLANT_ENTITY_ID,
        bindings={"sens_ess_soc": "Battery_SOC", "sens_power_consumers": "House_P"},
        triggers=[
            {
                "id": "grid_spike",
                "ehal_field": "sens_ess_soc",
                "signal_type": "analog",
                "on_change": "any",
                "label": "SOC",
            }
        ],
    )
    assert house["plant"]["ehal_bindings"]["sens_ess_soc"] == "Battery_SOC"
    assert house["plant"]["event_triggers"][0]["id"] == "grid_spike"

    house = apply_entity_bindings(
        house,
        profile_id="live",
        entity_id="ev1",
        bindings={
            "set_evcs_max_current": "EV_MaxA",
            "get_evcs_limit_soc": "EV_Limit",
        },
        triggers=[],
    )
    consumer = house["profiles"]["live"]["consumers"][0]
    assert consumer["ehal_bindings"]["set_evcs_max_current"] == "EV_MaxA"
    assert consumer["ehal_bindings"]["get_evcs_limit_soc"] == "EV_Limit"
