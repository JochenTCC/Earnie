"""UI-adjacent tests for entity-centric EHAL Loxone mapping save (2.4.k)."""
from __future__ import annotations

from ehal.ess_fields import ESS_BATTERY_MAPPING_KINDS, ess_field, ess_field_kind
from ui.ehal_loxone_mapping import (
    BATTERY_ENTITY_KIND,
    EV_FIELDS,
    FILTER_FIELDS,
    FLEX_FIELDS,
    PLANT_ENTITY_ID,
    PLANT_FIELDS,
    PROPOSAL_FIELDS,
    SCAN_ROW_KEYS,
    _NONE,
    _field_select_caption,
    _name_options,
    add_manual_marker_name,
    apply_battery_bindings,
    apply_entity_bindings,
    build_entity_rows,
    device_map_ehal_by_name,
    ehal_name_for_marker,
    enrich_structure_scan_rows,
    fields_for_battery,
    fields_for_consumer,
    is_known_marker_name,
    marker_to_ehal_lookup,
    proposal_for_mapping_field,
    resolve_field_select_default,
    structure_scan_row,
)


def test_fields_for_consumer_ev_vs_flex():
    assert "set_evcs_max_current" in fields_for_consumer({"type": "ev"})
    assert "get_evcs_limit_soc" in EV_FIELDS
    assert "get_evcs_soc_min_immediate" in EV_FIELDS
    assert "sens_power_consumers" in PLANT_FIELDS
    assert "sens_pv_energy" in PLANT_FIELDS
    assert "sens_grid_energy_import" in PLANT_FIELDS
    assert "sens_grid_energy_export" in PLANT_FIELDS
    assert "sens_ess_soc" not in PLANT_FIELDS
    assert "set_ess_active_power" not in PLANT_FIELDS
    assert "set_ess_source_select" not in PLANT_FIELDS
    assert "set_grid_export_power_limit" in PLANT_FIELDS
    assert "sens_energy_total" in FLEX_FIELDS
    assert "sens_energy_export" not in FLEX_FIELDS
    assert fields_for_consumer({"type": "thermal_annual"}) == FLEX_FIELDS + (
        "sens_temperature_heat_storage",
        "sens_temperature_heat_storage_low",
    )
    assert fields_for_consumer({"id": "wp", "type": "thermal_annual"}) == (
        "flex.wp.sens_power_act",
        "flex.wp.sens_consumer_active",
        "flex.wp.set_enable",
        "sens_temperature_heat_storage",
        "sens_temperature_heat_storage_low",
    )
    assert "get_filter_remaining_hours" in FILTER_FIELDS


def test_proposal_fields_cover_plant_and_battery_kinds():
    assert "set_grid_export_power_limit" in PROPOSAL_FIELDS
    for kind in ESS_BATTERY_MAPPING_KINDS:
        assert kind in PROPOSAL_FIELDS
    plant_fields = set(PLANT_FIELDS)
    battery_fields = set(fields_for_battery("bat1"))
    proposals = {f: {"marker_name": f"M_{f}", "confidence": 0.5} for f in PROPOSAL_FIELDS}
    for field in plant_fields | battery_fields:
        kind = ess_field_kind(field)
        if kind == "set_ess_source_select" or field == "set_ess_source_select":
            continue
        assert proposal_for_mapping_field(proposals, field), field


def test_proposal_for_mapping_field_pattern_b_and_miss():
    proposals = {
        "sens_ess_soc": {
            "marker_name": "Batterie_SoC",
            "confidence": 0.6,
            "source": "heuristic",
        }
    }
    hit = proposal_for_mapping_field(proposals, "ess.bat1.sens_ess_soc")
    assert hit["marker_name"] == "Batterie_SoC"
    assert proposal_for_mapping_field(proposals, "ess.bat1.sens_ess_power") == {}
    assert proposal_for_mapping_field({}, "sens_ess_soc") == {}
    assert proposal_for_mapping_field({"sens_ess_soc": "junk"}, "sens_ess_soc") == {}


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
    rows = build_entity_rows(
        house, "live", components_doc={"batteries": [], "pv_systems": []}
    )
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


def test_resolve_field_select_default_keeps_existing_over_proposal():
    # Runtime case: e_auto set_evcs_mode was displaced by SOCMinSofort proposal.
    assert (
        resolve_field_select_default("Earnie_EAuto_Modus", "Earnie_EAuto_SOCMinSofort")
        == "Earnie_EAuto_Modus"
    )
    assert (
        resolve_field_select_default("Earnie_EAuto_Soll_A", "Earnie_EAuto_MaxStrom")
        == "Earnie_EAuto_Soll_A"
    )
    assert resolve_field_select_default("", "Earnie_EAuto_SOCMinSofort") == (
        "Earnie_EAuto_SOCMinSofort"
    )
    assert resolve_field_select_default("", "") == ""


def test_build_entity_rows_includes_plant_and_consumers():
    house = {
        "plant": {"ehal_bindings": {"set_grid_export_power_limit": "ExportLimit"}},
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
    rows = build_entity_rows(house, "live", components_doc={"batteries": [], "pv_systems": []})
    ids = [r["id"] for r in rows]
    assert ids == [PLANT_ENTITY_ID, "ev1", "wp"]
    assert "set_ess_source_select" not in rows[0]["fields"]
    assert rows[0]["bindings"]["set_grid_export_power_limit"] == "ExportLimit"
    assert "sens_ess_soc" not in rows[0]["fields"]
    assert "set_evcs_max_current" in rows[1]["fields"]
    assert "set_evcs_current" not in rows[1]["fields"]
    assert "flex.wp.sens_power_act" in rows[2]["fields"]


def test_build_entity_rows_includes_batteries():
    house = {
        "plant": {},
        "profiles": {"live": {"id": "live", "consumers": []}},
    }
    components = {
        "batteries": [
            {
                "id": "house",
                "label": "Haus",
                "ehal_bindings": {
                    ess_field("house", "sens_ess_soc"): "Earnie_Batterie_SoC",
                },
            },
            {
                "id": "ps1",
                "label": "Delta",
                "type": "powerstation",
                "backing": "physical",
                "role": "standby_backup",
                "ehal_bindings": {},
            },
            {
                "id": "virt",
                "label": "Virtuell",
                "type": "powerstation",
                "backing": "virtual",
                "ehal_bindings": {},
            },
        ],
        "pv_systems": [],
    }
    rows = build_entity_rows(house, "live", components_doc=components)
    kinds = [(r["id"], r["kind"]) for r in rows]
    assert kinds[0] == (PLANT_ENTITY_ID, "plant")
    assert ("house", BATTERY_ENTITY_KIND) in kinds
    assert ("ps1", BATTERY_ENTITY_KIND) in kinds
    assert ("virt", BATTERY_ENTITY_KIND) not in kinds
    house_row = next(r for r in rows if r["id"] == "house")
    assert ess_field("house", "sens_ess_soc") in house_row["fields"]
    assert ess_field("house", "set_ess_source_select") not in house_row["fields"]
    assert house_row["bindings"][ess_field("house", "sens_ess_soc")] == (
        "Earnie_Batterie_SoC"
    )
    assert fields_for_battery("house", battery=house_row["battery"]) == house_row["fields"]
    ps_row = next(r for r in rows if r["id"] == "ps1")
    assert ess_field("ps1", "set_ess_source_select") in ps_row["fields"]


def test_apply_battery_bindings_rejects_virtual_powerstation():
    import pytest

    components = {
        "batteries": [
            {
                "id": "virt",
                "label": "V",
                "type": "powerstation",
                "backing": "virtual",
                "ehal_bindings": {},
            }
        ],
        "pv_systems": [],
    }
    with pytest.raises(ValueError, match="Virtual powerstation"):
        apply_battery_bindings(
            components,
            battery_id="virt",
            bindings={ess_field("virt", "sens_ess_soc"): "SoC"},
        )


def test_apply_battery_bindings_writes_components():
    components = {
        "batteries": [{"id": "house", "label": "Haus", "ehal_bindings": {}}],
        "pv_systems": [],
    }
    updated = apply_battery_bindings(
        components,
        battery_id="house",
        bindings={ess_field("house", "sens_ess_soc"): "SoC"},
    )
    assert updated["batteries"][0]["ehal_bindings"][
        ess_field("house", "sens_ess_soc")
    ] == "SoC"


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
    rows = build_entity_rows(
        house, "live", components_doc={"batteries": [], "pv_systems": []}
    )
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


def test_marker_to_ehal_lookup_reverse_binding():
    house = {
        "plant": {"ehal_bindings": {"sens_ess_soc": "Earnie_Batterie_SoC"}},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "waermepumpe",
                        "type": "thermal_annual",
                        "ehal_bindings": {
                            "flex.waermepumpe.set_enable": "Earnie_Waermepumpe_Freigabe",
                        },
                    }
                ],
            }
        },
    }
    lookup = marker_to_ehal_lookup(house, "live")
    assert lookup["Earnie_Waermepumpe_Freigabe"] == "flex.waermepumpe.set_enable"
    assert lookup["Earnie_Batterie_SoC"] == "sens_ess_soc"


def test_ehal_name_for_marker_binding_then_device_map():
    house = {
        "plant": {
            "ehal_bindings": {
                "flex.waermepumpe.set_enable": "Earnie_Waermepumpe_Freigabe",
            }
        },
        "profiles": {"live": {"id": "live", "consumers": []}},
    }
    assert (
        ehal_name_for_marker("Earnie_Waermepumpe_Freigabe", house, "live")
        == "flex.waermepumpe.set_enable"
    )
    # Unbound plant Merker → greenfield device map
    assert ehal_name_for_marker("Earnie_Netzleistung", house, "live") == (
        "sens_grid_power_active"
    )
    # Device map ehal_field null (watchdog only)
    assert ehal_name_for_marker("Earnie_Heartbeat", house, "live") == ""
    assert ehal_name_for_marker("Unknown_Custom", house, "live") == ""


def test_structure_scan_row_column_order():
    row = structure_scan_row(
        name="Earnie_SOC",
        ehal="sens_ess_soc",
        type_="http_probe",
        source="http_probe",
        room="Keller",
        category="Energie",
        uuid="abc-123",
    )
    assert tuple(row.keys()) == SCAN_ROW_KEYS
    assert list(row.keys())[-3:] == ["room", "category", "uuid"]


def test_enrich_structure_scan_rows_orders_and_resolves():
    house = {
        "plant": {},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "waermepumpe",
                        "type": "thermal_annual",
                        "ehal_bindings": {
                            "flex.waermepumpe.set_enable": "Earnie_Waermepumpe_Freigabe",
                        },
                    }
                ],
            }
        },
    }
    items = [
        {
            "name": "Earnie_Waermepumpe_Freigabe",
            "uuid": "u1",
            "type": "http_probe",
            "room": "Technik",
            "category": "HVAC",
            "source": "http_probe",
        },
        {
            "name": "Earnie_Heartbeat",
            "uuid": "",
            "type": "http_probe",
            "room": "",
            "category": "",
            "source": "http_probe",
        },
    ]
    rows = enrich_structure_scan_rows(items, house, "live")
    assert tuple(rows[0].keys()) == SCAN_ROW_KEYS
    assert rows[0]["ehal"] == "flex.waermepumpe.set_enable"
    assert rows[0]["uuid"] == "u1"
    assert rows[1]["ehal"] == ""
    assert device_map_ehal_by_name().get("Earnie_Netzleistung") == (
        "sens_grid_power_active"
    )
