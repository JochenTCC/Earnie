"""UI-adjacent tests for entity-centric EHAL Loxone mapping save (2.4.k)."""
from __future__ import annotations

from ui.ehal_loxone_mapping import (
    EV_FIELDS,
    FILTER_FIELDS,
    FLEX_FIELDS,
    PLANT_ENTITY_ID,
    PLANT_FIELDS,
    _NONE,
    _field_select_caption,
    _name_options,
    add_manual_marker_name,
    apply_entity_bindings,
    build_entity_rows,
    fields_for_consumer,
    is_known_marker_name,
)


def test_fields_for_consumer_ev_vs_flex():
    assert "set_evcs_max_current" in fields_for_consumer({"type": "ev"})
    assert "get_evcs_limit_soc" in EV_FIELDS
    assert "get_evcs_soc_min_immediate" in EV_FIELDS
    assert "sens_power_consumers" in PLANT_FIELDS
    assert fields_for_consumer({"type": "thermal_annual"}) == FLEX_FIELDS
    assert fields_for_consumer({"id": "wp", "type": "thermal_annual"}) == (
        "flex.wp.sens_power_act",
        "flex.wp.set_enable",
        "flex.wp.set_power_setpoint",
    )
    assert "get_filter_remaining_hours" in FILTER_FIELDS


def test_fields_for_consumer_pool_filter_includes_filter_roles():
    fields = fields_for_consumer({"id": "pool_filter", "type": "flexible"})
    assert "flex.pool_filter.sens_power_act" in fields
    assert "get_filter_remaining_hours" in fields
    assert "sens_filter_active" in fields
    assert "get_filter_native_start_hour" in fields
    assert "get_filter_native_duration_hours" in fields
    assert "flex.pool_filter.set_enable" in fields
    assert "flex.pool_filter.set_power_setpoint" not in fields


def test_build_entity_rows_pool_filter_only():
    house = {
        "plant": {},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "pool",
                        "label": "Pool",
                        "type": "thermal_rc",
                        "use_profile_csv": False,
                    },
                    {
                        "id": "pool_filter",
                        "label": "Pool Filter",
                        "type": "flexible",
                        "ehal_bindings": {
                            "get_filter_remaining_hours": "Earnie_Pool_Filter_Sollstunden",
                        },
                    },
                ],
            }
        },
    }
    rows = build_entity_rows(house, "live")
    ids = [r["id"] for r in rows]
    assert ids == [PLANT_ENTITY_ID, "pool", "pool_filter"]
    filt = next(r for r in rows if r["id"] == "pool_filter")
    assert "get_filter_remaining_hours" in filt["fields"]
    assert "flex.pool_filter.sens_power_act" in filt["fields"]
    assert filt["bindings"]["get_filter_remaining_hours"] == (
        "Earnie_Pool_Filter_Sollstunden"
    )


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
    assert "flex.wp.sens_power_act" in rows[2]["fields"]


def test_build_entity_rows_thermal_rc_alone_has_no_synthetic_filter():
    house = {
        "plant": {},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "pool",
                        "label": "Pool",
                        "type": "thermal_rc",
                        "use_profile_csv": False,
                    }
                ],
            }
        },
    }
    rows = build_entity_rows(house, "live")
    ids = [r["id"] for r in rows]
    assert ids == [PLANT_ENTITY_ID, "pool"]
    assert "pool_filter" not in ids
    pool = rows[1]
    assert "sens_temperature_water" in pool["fields"]


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
    )
    assert house["plant"]["ehal_bindings"]["sens_ess_soc"] == "Battery_SOC"
    assert "event_triggers" not in house["plant"]

    house = apply_entity_bindings(
        house,
        profile_id="live",
        entity_id="ev1",
        bindings={
            "set_evcs_max_current": "EV_MaxA",
            "get_evcs_limit_soc": "EV_Limit",
        },
    )
    consumer = house["profiles"]["live"]["consumers"][0]
    assert consumer["ehal_bindings"]["set_evcs_max_current"] == "EV_MaxA"
    assert consumer["ehal_bindings"]["get_evcs_limit_soc"] == "EV_Limit"


def test_apply_entity_bindings_writes_pool_filter_ehal():
    house = {
        "plant": {},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "pool",
                        "label": "Pool",
                        "type": "thermal_rc",
                        "use_profile_csv": False,
                    },
                    {
                        "id": "pool_filter",
                        "label": "Pool Filter",
                        "type": "generic",
                    },
                ],
            }
        },
    }
    house = apply_entity_bindings(
        house,
        profile_id="live",
        entity_id="pool_filter",
        bindings={"get_filter_remaining_hours": "Earnie_Pool_Filter_Sollstunden"},
    )
    filt = house["profiles"]["live"]["consumers"][1]
    assert filt["ehal_bindings"] == {
        "get_filter_remaining_hours": "Earnie_Pool_Filter_Sollstunden",
    }
    assert "swimspa_filter_bindings" not in house["profiles"]["live"]["consumers"][0]


def test_name_options_merges_manual_names():
    options = _name_options(
        [{"name": "From_Probe"}],
        ["Saved_Binding"],
        ["Manual_Merker", "From_Probe"],
    )
    assert options[0] == _NONE
    assert "From_Probe" in options
    assert "Saved_Binding" in options
    assert "Manual_Merker" in options
    assert options.count("From_Probe") == 1


def test_add_manual_marker_name_empty_and_duplicate():
    names, hint = add_manual_marker_name([], "  ")
    assert names == []
    assert hint is not None

    names, hint = add_manual_marker_name(["Earnie_SOC"], "earnie_soc")
    assert names == ["Earnie_SOC"]
    assert hint is not None

    names, hint = add_manual_marker_name(
        [],
        "New_Merker",
        also_known=["New_Merker"],
    )
    assert names == []
    assert hint is not None

    names, hint = add_manual_marker_name(["A"], "B")
    assert names == ["A", "B"]
    assert hint is None


def test_is_known_marker_name_casefold():
    options = [_NONE, "Earnie_SOC", "House_P"]
    assert is_known_marker_name("earnie_soc", options)
    assert not is_known_marker_name("Brand_New", options)
    assert not is_known_marker_name(_NONE, options)
    assert not is_known_marker_name("", options)
