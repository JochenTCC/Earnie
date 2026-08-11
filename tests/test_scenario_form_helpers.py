"""Tests für ui.scenario_form_helpers."""
from __future__ import annotations

import pytest

from ui.scenario_form_helpers import (
    NONE_LABEL,
    NEW_SCENARIO_OPTION,
    build_scenario_settings,
    default_label_index,
    default_scenario_pick,
    lookup_entity_id,
    new_scenario_template,
    normalize_scenario_form_snapshot,
    options_for_entities,
    ordered_user_scenario_ids,
    read_scenario_form_snapshot,
    resolve_scenario_id,
    scenario_form_is_dirty,
    scenario_new_option,
    scenario_session_scope,
    scoped_widget_key,
    store_scenario_form_baseline,
)


def test_lookup_entity_id_none_returns_empty():
    mapping = {"Label": "bat"}
    assert lookup_entity_id(mapping, None) == ""


def test_lookup_entity_id_unknown_returns_empty():
    mapping = {"Label": "bat"}
    assert lookup_entity_id(mapping, "unbekannt") == ""


def test_lookup_entity_id_resolves_label():
    mapping = {"Meine Batterie": "bat1"}
    assert lookup_entity_id(mapping, "Meine Batterie") == "bat1"


def test_options_empty_without_allow_none():
    labels, mapping = options_for_entities([], allow_none=False)
    assert labels == []
    assert mapping == {}


def test_options_empty_with_allow_none():
    labels, mapping = options_for_entities([], allow_none=True)
    assert labels == [NONE_LABEL]
    assert mapping[NONE_LABEL] == ""


def test_options_builds_labels_and_mapping():
    items = [{"id": "pv1", "label": "Dach"}]
    labels, mapping = options_for_entities(items)
    assert labels == ["Dach"]
    assert mapping["Dach"] == "pv1"


def test_options_disambiguates_duplicate_labels():
    items = [
        {"id": "a", "label": "Dach"},
        {"id": "b", "label": "Dach"},
    ]
    labels, mapping = options_for_entities(items)
    assert labels == ["Dach", "Dach (b)"]
    assert mapping["Dach"] == "a"
    assert mapping["Dach (b)"] == "b"


def test_format_entity_option_strips_id_suffix():
    from ui.scenario_form_helpers import format_entity_option

    assert format_entity_option("Dach (pv1)") == "Dach"
    assert format_entity_option(NONE_LABEL) == NONE_LABEL
    assert format_entity_option("— noch keine batterie —") == "— noch keine batterie —"


def test_default_label_index_finds_id():
    options = ["— keine —", "Batterie"]
    mapping = {"— keine —": "", "Batterie": "bat"}
    assert default_label_index(options, "bat", mapping) == 1


def test_default_label_index_missing_returns_zero():
    options = ["Batterie"]
    assert default_label_index(options, "missing") == 0


def test_scenario_session_scope_new_uses_placeholder():
    assert scenario_session_scope(NEW_SCENARIO_OPTION, is_new=True) == "__new__"
    assert scenario_session_scope("live", is_new=False) == "live"


def test_scenario_new_option_gated():
    assert scenario_new_option(allow_new=True) == NEW_SCENARIO_OPTION
    assert scenario_new_option(allow_new=False) is None


def test_default_scenario_pick_prefers_live():
    assert (
        default_scenario_pick(
            live_id="live",
            scenario_ids=["other", "live"],
            allow_new=False,
        )
        == "live"
    )


def test_default_scenario_pick_without_live_uses_first_when_new_disabled():
    assert (
        default_scenario_pick(
            live_id="missing",
            scenario_ids=["a", "b"],
            allow_new=False,
        )
        == "a"
    )


def test_default_scenario_pick_empty_allows_new_when_enabled():
    assert (
        default_scenario_pick(
            live_id="live",
            scenario_ids=[],
            allow_new=True,
        )
        == NEW_SCENARIO_OPTION
    )


def test_default_scenario_pick_empty_without_new_keeps_live_id():
    assert (
        default_scenario_pick(
            live_id="live",
            scenario_ids=[],
            allow_new=False,
        )
        == "live"
    )


def test_new_scenario_template_clones_live_settings():
    scenarios = [
        {
            "id": "live",
            "label": "Live",
            "settings": {"battery_id": "bat1", "house_profile_id": "home"},
        }
    ]
    template = new_scenario_template(scenarios, source_id="live", live_id="live")
    assert template["label"] == "Live copy"
    assert template["settings"]["battery_id"] == "bat1"
    assert template["settings"]["house_profile_id"] == "home"
    assert template["enabled"] is True


def test_new_scenario_template_clones_last_selected_not_live():
    scenarios = [
        {
            "id": "live",
            "label": "Live",
            "enabled": True,
            "settings": {"battery_id": "bat_live"},
            "own_reference": False,
        },
        {
            "id": "ohne_pv",
            "label": "Ohne PV",
            "enabled": False,
            "settings": {
                "battery_id": "bat1",
                "pv_system_ids": ["pv1", "pv2"],
            },
            "own_reference": True,
        },
    ]
    template = new_scenario_template(
        scenarios, source_id="ohne_pv", live_id="live"
    )
    assert template["label"] == "Ohne PV copy"
    assert template["enabled"] is False
    assert template["own_reference"] is True
    assert template["settings"]["battery_id"] == "bat1"
    assert template["settings"]["pv_system_ids"] == ["pv1", "pv2"]


def test_new_scenario_template_label_collision_gets_suffix():
    scenarios = [
        {"id": "live", "label": "Live", "settings": {}},
        {"id": "live_copy", "label": "Live copy", "settings": {}},
    ]
    template = new_scenario_template(scenarios, source_id="live", live_id="live")
    assert template["label"] == "Live copy 2"


def test_new_scenario_template_unknown_source_falls_back_to_live():
    scenarios = [
        {
            "id": "live",
            "label": "Live",
            "settings": {"battery_id": "bat_live"},
        }
    ]
    template = new_scenario_template(
        scenarios, source_id="missing", live_id="live"
    )
    assert template["label"] == "Live copy"
    assert template["settings"]["battery_id"] == "bat_live"


def test_new_scenario_template_without_source_uses_empty_settings():
    template = new_scenario_template([], source_id="live", live_id="live")
    assert template["label"] == "Mein Szenario"
    assert template["settings"] == {}


def test_new_scenario_template_deepcopies_nested_settings():
    scenarios = [
        {
            "id": "live",
            "label": "Live",
            "settings": {"pv_system_ids": ["pv1"]},
        }
    ]
    template = new_scenario_template(scenarios, source_id="live", live_id="live")
    template["settings"]["pv_system_ids"].append("pv2")
    assert scenarios[0]["settings"]["pv_system_ids"] == ["pv1"]


def test_resolve_scenario_id_keeps_existing_id():
    assert (
        resolve_scenario_id(
            is_new=False,
            existing_id="live",
            label="Neue Bezeichnung",
            scenario_ids={"live", "other"},
        )
        == "live"
    )


def test_resolve_scenario_id_derives_from_label_for_new():
    assert (
        resolve_scenario_id(
            is_new=True,
            existing_id="",
            label="Ohne PV",
            scenario_ids={"live"},
        )
        == "ohne_pv"
    )


def test_resolve_scenario_id_avoids_collisions_for_new():
    assert (
        resolve_scenario_id(
            is_new=True,
            existing_id="",
            label="Live",
            scenario_ids={"live"},
        )
        == "live_2"
    )


def test_scenario_form_is_dirty_when_label_changed():
    session = {
        scoped_widget_key("live", "scenario_label"): "Geändert",
        scoped_widget_key("live", "scenario_profile"): "— keine —",
        scoped_widget_key("live", "scenario_battery"): "— keine —",
        scoped_widget_key("live", "scenario_pv"): [],
        scoped_widget_key("live", "scenario_import"): "— keine —",
        scoped_widget_key("live", "scenario_export"): "— keine —",
    }
    store_scenario_form_baseline(
        session,
        "live",
        {"id": "live", "label": "Live", "settings": {}},
    )
    assert scenario_form_is_dirty(
        session,
        "live",
        profiles={},
        batteries=[],
        pv_systems=[],
        import_tariffs=[],
        export_tariffs=[],
    ) is True


def test_scenario_form_is_clean_when_matching_baseline():
    session = {
        scoped_widget_key("live", "scenario_label"): "Live",
        scoped_widget_key("live", "scenario_profile"): "— keine —",
        scoped_widget_key("live", "scenario_battery"): "— keine —",
        scoped_widget_key("live", "scenario_pv"): [],
        scoped_widget_key("live", "scenario_import"): "— keine —",
        scoped_widget_key("live", "scenario_export"): "— keine —",
    }
    store_scenario_form_baseline(
        session,
        "live",
        {"id": "live", "label": "Live", "settings": {}},
    )
    assert scenario_form_is_dirty(
        session,
        "live",
        profiles={},
        batteries=[],
        pv_systems=[],
        import_tariffs=[],
        export_tariffs=[],
    ) is False


def test_read_scenario_form_snapshot_resolves_entity_ids():
    batteries = [{"id": "bat1", "label": "Speicher"}]
    session = {
        scoped_widget_key("live", "scenario_label"): "Live",
        scoped_widget_key("live", "scenario_profile"): "— keine —",
        scoped_widget_key("live", "scenario_battery"): "Speicher",
        scoped_widget_key("live", "scenario_pv"): [],
        scoped_widget_key("live", "scenario_import"): "— keine —",
        scoped_widget_key("live", "scenario_export"): "— keine —",
    }
    snapshot = read_scenario_form_snapshot(
        session,
        "live",
        profiles={},
        batteries=batteries,
        pv_systems=[],
        import_tariffs=[],
        export_tariffs=[],
    )
    assert snapshot["settings"]["battery_id"] == "bat1"


def test_build_scenario_settings_basic_refs():
    settings = build_scenario_settings(
        battery_id="",
        pv_system_ids=[],
        import_tariff_id="imp",
        export_tariff_id="exp",
        house_profile_id="home",
    )
    assert settings == {
        "import_tariff_id": "imp",
        "export_tariff_id": "exp",
        "house_profile_id": "home",
    }
    assert "netzentgelt_cent_kwh_override" not in settings
    assert "pv_system_ids" not in settings


def test_build_scenario_settings_stores_pv_system_ids():
    settings = build_scenario_settings(
        battery_id="bat",
        pv_system_ids=["a", "b"],
        import_tariff_id="imp",
        export_tariff_id="exp",
        house_profile_id="home",
    )
    assert settings["pv_system_ids"] == ["a", "b"]
    assert "pv_system_id" not in settings


def test_build_scenario_settings_use_imported_pv():
    settings = build_scenario_settings(
        battery_id="",
        import_tariff_id="imp",
        export_tariff_id="exp",
        house_profile_id="home",
        use_imported_pv=True,
    )
    assert settings["use_imported_pv"] is True
    omitted = build_scenario_settings(
        battery_id="",
        import_tariff_id="imp",
        export_tariff_id="exp",
        house_profile_id="home",
        use_imported_pv=False,
    )
    assert "use_imported_pv" not in omitted


def test_normalize_scenario_form_snapshot_legacy_pv_system_id_rejected():
    with pytest.raises(ValueError, match="pv_system_ids"):
        normalize_scenario_form_snapshot(
            {
                "label": "Live",
                "settings": {"pv_system_id": "roof", "battery_id": "bat1"},
            },
        )


def test_normalize_scenario_form_snapshot_strips_geo_override():
    snapshot = normalize_scenario_form_snapshot(
        {
            "label": "Live",
            "settings": {
                "battery_id": "bat1",
                "house_profile_id": "home",
                "latitude": 1.0,
                "longitude": 2.0,
                "timezone_name": "UTC",
            },
        },
    )
    assert snapshot["settings"] == {
        "battery_id": "bat1",
        "house_profile_id": "home",
    }


def test_normalize_scenario_form_snapshot_keeps_label_and_settings():
    snapshot = normalize_scenario_form_snapshot(
        {"id": "variant_a", "label": "Variante A", "settings": {"battery_id": "bat1"}},
    )
    assert snapshot == {
        "label": "Variante A",
        "enabled": True,
        "settings": {"battery_id": "bat1"},
    }
    assert "id" not in snapshot


def test_normalize_scenario_form_snapshot_keeps_enabled_false():
    snapshot = normalize_scenario_form_snapshot(
        {
            "label": "Off",
            "enabled": False,
            "settings": {"battery_id": "bat1"},
        },
    )
    assert snapshot["enabled"] is False


def test_normalize_scenario_form_snapshot_keeps_own_reference():
    snapshot = normalize_scenario_form_snapshot(
        {
            "label": "Ref",
            "own_reference": True,
            "settings": {"battery_id": "bat1"},
        },
    )
    assert snapshot["own_reference"] is True


def test_ordered_user_scenario_ids_live_first_then_file_order():
    ordered = ordered_user_scenario_ids(
        ["zebra", "live", "alpha"],
        live_scenario_id="live",
        labels={"zebra": "Zebra", "live": "Live", "alpha": "Alpha"},
    )
    assert ordered == ["live", "zebra", "alpha"]


def test_ordered_user_scenario_ids_preserves_non_live_input_order():
    ordered = ordered_user_scenario_ids(
        ["b", "a", "live"],
        live_scenario_id="live",
        labels={"b": "beta", "a": "Alpha", "live": "Live"},
    )
    assert ordered == ["live", "b", "a"]


def test_ordered_user_scenario_ids_missing_live_keeps_input_order():
    ordered = ordered_user_scenario_ids(
        ["z", "a"],
        live_scenario_id="live",
        labels={"z": "Zed", "a": "Able"},
    )
    assert ordered == ["z", "a"]


def test_ordered_user_scenario_ids_dedupes_and_skips_blank():
    ordered = ordered_user_scenario_ids(
        ["live", "", "b", "live", "a"],
        live_scenario_id="live",
        labels={"live": "Live", "b": "B", "a": "A"},
    )
    assert ordered == ["live", "b", "a"]
