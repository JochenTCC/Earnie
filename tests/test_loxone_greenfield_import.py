"""Tests for greenfield Loxone Merker + EFM import (2.4.n P2)."""
from __future__ import annotations

import json
from pathlib import Path

from house_config.profiles_store import (
    normalize_house_profiles_document,
    save_house_profiles_document,
)
from integrations.loxone_greenfield_import import (
    apply_typed_matches,
    ensure_live_profile,
    load_device_map,
    match_controls,
    merge_efm,
    probe_marker_names,
    run_greenfield_import,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "loxapp3_greenfield.json"


def _doc() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _empty_house() -> dict:
    return {"profiles": [], "plant": {}}


def test_load_device_map_has_markers():
    dmap = load_device_map()
    assert dmap["version"] == 1
    assert any(m.get("name") == "Earnie_Heartbeat" for m in dmap["markers"])


def test_match_skips_heartbeat_and_binds_plant():
    matches, report = match_controls(_doc(), load_device_map())
    assert "Earnie_Heartbeat" in report.skipped_markers
    assert "Earnie_Heartbeat" not in report.matched_markers
    plant = next(m for m in matches if m.entity_kind == "plant")
    assert plant.bindings["sens_ess_soc"] == "Earnie_Batterie_SoC"
    assert plant.bindings["set_ess_mode"] == "Earnie_Steuerbefehl"
    assert plant.bindings["set_ess_charge_power_limit"] == "Earnie_LadeLeistungs-Limit"


def test_match_wp_and_ev_groups():
    matches, _report = match_controls(_doc(), load_device_map())
    by_group = {m.group_key: m for m in matches}
    wp = by_group["Earnie_Waermepumpe_"]
    assert wp.hk_type == "thermal_annual"
    assert wp.bindings["flex.waermepumpe.sens_power_act"] == "Earnie_Waermepumpe_Leistung"
    assert wp.bindings["flex.waermepumpe.set_enable"] == "Earnie_Waermepumpe_Freigabe"
    ev = by_group["Earnie_EAuto_"]
    assert ev.hk_type == "ev"
    assert ev.bindings["sens_evcs_active_power"] == "Earnie_EAuto_Leistung"
    assert ev.bindings["flex.e_auto.sens_power_act"] == "Earnie_EAuto_Leistung"
    assert ev.bindings["set_evcs_max_current"] == "Earnie_EAuto_Soll_A"


def test_alarm_clock_tna_merges_onto_ev_with_power():
    """AlarmClock Bezeichnung → get_evcs_ready_by_time on EV that has Zähler/power."""
    from integrations.loxone_greenfield_import import (
        extract_alarm_clocks,
        merge_alarm_clock_ready_by,
    )

    assert extract_alarm_clocks(_doc()) == ["Ladewecker"]
    result = run_greenfield_import(_doc(), _empty_house())
    house = result["house_doc"]
    pid = result["report"]["profile_id"]
    consumers = house["profiles"][pid]["consumers"]
    evs = [c for c in consumers if c.get("type") == "ev"]
    assert len(evs) >= 1
    assert evs[0]["ehal_bindings"]["get_evcs_ready_by_time"] == "Ladewecker"
    assert f"{evs[0]['id']}:Ladewecker" in result["report"]["alarm_clock_bound"]
    # Idempotent: existing binding kept
    house2 = merge_alarm_clock_ready_by(house, _doc(), profile_id=pid)
    ev2 = next(c for c in house2["profiles"][pid]["consumers"] if c.get("type") == "ev")
    assert ev2["ehal_bindings"]["get_evcs_ready_by_time"] == "Ladewecker"


def test_match_merges_legacy_wp_alias_into_waermepumpe(monkeypatch):
    """Mixed Earnie_Waermepumpe_* + Earnie_WP_* must yield one thermal_annual."""
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    empty_doc = {"controls": {}}
    extra = {
        "Earnie_Waermepumpe_Leistung",
        "Earnie_WP_Freigabe",
    }
    matches, _report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    wp_matches = [m for m in matches if m.hk_type == "thermal_annual"]
    assert len(wp_matches) == 1
    assert wp_matches[0].group_key == "Earnie_Waermepumpe_"
    assert wp_matches[0].bindings["flex.waermepumpe.sens_power_act"] == "Earnie_Waermepumpe_Leistung"
    assert wp_matches[0].bindings["flex.waermepumpe.set_enable"] == "Earnie_WP_Freigabe"
    house, pid = ensure_live_profile(_empty_house())
    house = apply_typed_matches(house, matches, profile_id=pid)
    consumers = house["profiles"][pid]["consumers"]
    thermals = [c for c in consumers if c["type"] == "thermal_annual"]
    assert len(thermals) == 1
    assert thermals[0]["ehal_bindings"]["flex.waermepumpe.sens_power_act"] == "Earnie_Waermepumpe_Leistung"
    assert thermals[0]["ehal_bindings"]["flex.waermepumpe.set_enable"] == "Earnie_WP_Freigabe"
    normalize_house_profiles_document(
        {"profiles": [dict(house["profiles"][pid], id=pid)]}
    )


def test_ensure_live_profile_bootstraps_empty():
    house, pid = ensure_live_profile({"profiles": []})
    assert pid == "live"
    assert "live" in house["profiles"]
    assert house["profiles"]["live"]["consumers"] == []


def test_match_controls_unions_http_probe_extra_names():
    """Probe hits work without LoxAPP3 visualization entries."""
    empty_doc = {"controls": {}}
    extra = {
        "Earnie_Waermepumpe_Leistung",
        "Earnie_Waermepumpe_Freigabe",
        "Earnie_Batterie_SoC",
    }
    matches, report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    assert "Earnie_Waermepumpe_Leistung" in report.matched_markers
    plant = next(m for m in matches if m.entity_kind == "plant")
    assert plant.bindings["sens_ess_soc"] == "Earnie_Batterie_SoC"
    wp = next(m for m in matches if m.group_key == "Earnie_Waermepumpe_")
    assert wp.bindings["flex.waermepumpe.set_enable"] == "Earnie_Waermepumpe_Freigabe"


def test_match_pool_is_thermal_rc():
    matches, _report = match_controls(_doc(), load_device_map())
    pool = next(m for m in matches if m.entity_kind == "pool")
    assert pool.hk_type == "thermal_rc"
    filt = next(m for m in matches if m.entity_kind == "pool_filter")
    assert filt.hk_type == "generic"


def test_slug_match_waschmaschine_creates_generic_consumer():
    empty_doc = {"controls": {}}
    extra = {
        "Earnie_Verbraucher_Waschmaschine_Leistung",
        "Earnie_Verbraucher_Waschmaschine_Freigabe",
        "Earnie_Verbraucher_Waschmaschine_Ziel_kW",
    }
    matches, report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    assert any("Waschmaschine" in n for n in report.matched_markers)
    cons = [m for m in matches if m.entity_kind == "generic"]
    assert len(cons) == 1
    wm = cons[0]
    assert wm.label == "Waschmaschine"
    assert wm.hk_type == "generic"
    assert wm.bindings["flex.waschmaschine.sens_power_act"] == "Earnie_Verbraucher_Waschmaschine_Leistung"
    assert wm.bindings["flex.waschmaschine.set_enable"] == "Earnie_Verbraucher_Waschmaschine_Freigabe"
    assert wm.bindings["flex.waschmaschine.set_power_setpoint"] == "Earnie_Verbraucher_Waschmaschine_Ziel_kW"
    house, pid = ensure_live_profile(_empty_house())
    house = apply_typed_matches(house, matches, profile_id=pid)
    by_id = {c["id"]: c for c in house["profiles"][pid]["consumers"]}
    assert "waschmaschine" in by_id
    assert by_id["waschmaschine"]["ehal_bindings"]["flex.waschmaschine.sens_power_act"].endswith(
        "Waschmaschine_Leistung"
    )


def test_slug_match_ev_creates_ev_consumer():
    empty_doc = {"controls": {}}
    extra = {
        "Earnie_EAuto_Garage_Soll_A",
        "Earnie_EAuto_Garage_Modus",
        "Earnie_EAuto_Garage_Leistung",
    }
    matches, _report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    evs = [m for m in matches if m.entity_kind == "ev"]
    assert len(evs) == 1
    assert evs[0].label == "Garage"
    assert evs[0].bindings["set_evcs_max_current"] == "Earnie_EAuto_Garage_Soll_A"
    assert evs[0].bindings["sens_evcs_active_power"] == "Earnie_EAuto_Garage_Leistung"
    house, pid = ensure_live_profile(_empty_house())
    house = apply_typed_matches(house, matches, profile_id=pid)
    by_id = {c["id"]: c for c in house["profiles"][pid]["consumers"]}
    assert "garage" in by_id
    assert by_id["garage"]["type"] == "ev"


def test_slug_match_casefold_dedupes_variants():
    empty_doc = {"controls": {}}
    extra = {
        "Earnie_Verbraucher_Waschmaschine_Leistung",
        "earnie_verbraucher_waschmaschine_leistung",
        "Earnie_Verbraucher_Waschmaschine_Freigabe",
    }
    matches, _report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    generics = [m for m in matches if m.entity_kind == "generic"]
    assert len(generics) == 1
    assert len(generics[0].bindings) >= 2


def test_slug_match_pool_filter_longest_prefix():
    empty_doc = {"controls": {}}
    extra = {
        "Earnie_Pool_Filter_Freigabe",
        "Earnie_Pool_Filter_aktiv",
        "Earnie_Pool_P_act",
        "Earnie_Pool_Freigabe",
    }
    matches, _report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    by_kind = {}
    for m in matches:
        by_kind.setdefault(m.entity_kind, []).append(m)
    assert len(by_kind.get("pool_filter", [])) == 1
    assert len(by_kind.get("pool", [])) == 1
    assert by_kind["pool_filter"][0].bindings["flex.pool_filter.set_enable"] == (
        "Earnie_Pool_Filter_Freigabe"
    )


def test_exact_plant_case_insensitive():
    empty_doc = {"controls": {}}
    extra = {"earnie_batterie_soc", "EARNIE_STEUERBEFEHL"}
    matches, _report = match_controls(empty_doc, load_device_map(), extra_names=extra)
    plant = next(m for m in matches if m.entity_kind == "plant")
    assert plant.bindings["sens_ess_soc"] == "earnie_batterie_soc"
    assert plant.bindings["set_ess_mode"] == "EARNIE_STEUERBEFEHL"


def test_probe_marker_names_treats_403_as_present(monkeypatch):
    calls: list[str] = []

    class _Resp:
        def __init__(self, code: str, http: int = 200):
            self.status_code = http
            self.content = b"{}"
            self._code = code

        def json(self):
            return {"LL": {"Code": self._code, "value": ""}}

    def fake_get(url, auth=None, timeout=5.0):
        calls.append(url)
        if "DOES_NOT" in url:
            return _Resp("404", 404)
        if "Earnie_Heartbeat" in url:
            return _Resp("403")
        return _Resp("200")

    monkeypatch.setattr(
        "integrations.loxone_greenfield_import.requests.get", fake_get
    )
    result = probe_marker_names(
        ["Earnie_Heartbeat", "Earnie_Waermepumpe_Freigabe", "DOES_NOT"],
        host="192.0.2.1",
        username="u",
        password="p",
    )
    assert "Earnie_Heartbeat" in result.present
    assert "Earnie_Waermepumpe_Freigabe" in result.present
    assert "DOES_NOT" in result.missing
    assert len(calls) == 3


def test_run_import_creates_typed_and_efm_consumers():
    result = run_greenfield_import(_doc(), _empty_house())
    house = result["house_doc"]
    report = result["report"]
    assert report["profile_id"] == "live"
    plant = house["plant"]["ehal_bindings"]
    assert plant["sens_ess_soc"] == "Earnie_Batterie_SoC"
    assert plant["set_ess_active_power"] == "Earnie_Batterie_Sollleistung"
    consumers = house["profiles"]["live"]["consumers"]
    by_id = {c["id"]: c for c in consumers}
    assert "waermepumpe" in by_id
    assert by_id["waermepumpe"]["type"] == "thermal_annual"
    assert (
        by_id["waermepumpe"]["ehal_bindings"]["flex.waermepumpe.set_enable"]
        == "Earnie_Waermepumpe_Freigabe"
    )
    assert "e_auto" in by_id
    assert by_id["e_auto"]["type"] == "ev"
    assert by_id["e_auto"]["battery_capacity_kwh"] == 50.0
    assert by_id["e_auto"]["nominal_power_kw"] == 3.5
    assert by_id["e_auto"]["min_power_kw"] == 1.4
    assert by_id["e_auto"]["min_on_quarterhours"] == 4
    assert "pool_swimspa" in by_id or "pool_swim_spa" in by_id or any(
        c["type"] == "thermal_rc" for c in consumers
    )
    # EFM loads that do not collide with Earnie_* power names are created
    from ehal.flex_fields import is_flex_sens_power_act_field

    assert any(
        is_flex_sens_power_act_field(k) and v == "Zähler Kochen"
        for c in consumers
        for k, v in (c.get("ehal_bindings") or {}).items()
    )
    assert report["efm_created"]
    # Zähler labels stripped on create
    assert by_id["kochen"]["label"] == "Kochen"
    assert "zaehler_kochen" not in by_id


def test_efm_merges_swimspa_and_wallbox_onto_typed():
    """Zähler Swimspa / Wallbox merge into typed pool / EV (no duplicate generics)."""
    from ehal.flex_fields import flex_sens_power_act

    result = run_greenfield_import(_doc(), _empty_house())
    consumers = result["house_doc"]["profiles"]["live"]["consumers"]
    by_id = {c["id"]: c for c in consumers}
    pool = next(c for c in consumers if c["type"] == "thermal_rc")
    assert pool["ehal_bindings"][flex_sens_power_act(pool["id"])] == "Zähler Swimspa"
    assert by_id["e_auto"]["ehal_bindings"]["sens_evcs_active_power"] == "Zähler Wallbox"
    assert (
        by_id["waermepumpe"]["ehal_bindings"][flex_sens_power_act("waermepumpe")]
        == "Zähler Wärmepumpe"
    )
    generic_ids = {c["id"] for c in consumers if c["type"] == "generic"}
    assert not {"zaehler_swimspa", "swimspa", "zaehler_wallbox", "wallbox", "zaehler_waermepumpe"} & generic_ids


def test_apply_typed_merges_same_id_ev():
    """Second Merker group with same slug merges into existing EV."""
    empty_doc = {"controls": {}}
    first = {
        "Earnie_EAuto_Garage_Soll_A",
        "Earnie_EAuto_Garage_Leistung",
    }
    matches, _ = match_controls(empty_doc, load_device_map(), extra_names=first)
    house, pid = ensure_live_profile(_empty_house())
    house = apply_typed_matches(house, matches, profile_id=pid)
    second = {"Earnie_EAuto_Garage_Modus", "Earnie_EAuto_Garage_Angeschlossen"}
    matches2, _ = match_controls(empty_doc, load_device_map(), extra_names=second)
    house = apply_typed_matches(house, matches2, profile_id=pid)
    evs = [c for c in house["profiles"][pid]["consumers"] if c["type"] == "ev"]
    assert len(evs) == 1
    assert evs[0]["id"] == "garage"
    assert "set_evcs_mode" in evs[0]["ehal_bindings"]
    assert "sens_evcs_connected" in evs[0]["ehal_bindings"]
    assert "set_evcs_max_current" in evs[0]["ehal_bindings"]


def test_efm_duplicate_power_skips_create():
    from ehal.flex_fields import flex_sens_power_act, is_flex_sens_power_act_field

    dmap = load_device_map()
    matches, report = match_controls(_doc(), dmap)
    house, pid = ensure_live_profile(_empty_house())
    house = apply_typed_matches(house, matches, profile_id=pid, report=report)
    # Force typed power name to equal an EFM load Bezeichnung
    consumers = house["profiles"][pid]["consumers"]
    wp = next(c for c in consumers if c["type"] == "thermal_annual")
    wp["ehal_bindings"][flex_sens_power_act(wp["id"])] = "Zähler Wärmepumpe"
    house = merge_efm(house, _doc(), profile_id=pid, report=report)
    powers = [
        str(v)
        for c in house["profiles"][pid]["consumers"]
        for k, v in (c.get("ehal_bindings") or {}).items()
        if is_flex_sens_power_act_field(str(k))
    ]
    assert powers.count("Zähler Wärmepumpe") == 1
    assert "Zähler Wärmepumpe" in report.efm_skipped_typed


def test_efm_fills_plant_when_earnie_grid_absent():
    mini = {
        "rooms": {"r1": {"name": "Technik"}},
        "cats": {"c1": {"name": "Energie"}},
        "controls": {
            "uuid-efm": {
                "name": "EFM",
                "type": "EFM",
                "details": {
                    "nodes": [
                        {
                            "title": "Zähler Netz",
                            "ctrlUuid": "uuid-grid",
                            "nodeType": "Grid",
                        }
                    ]
                },
            },
            "uuid-grid": {
                "name": "Zähler Netz",
                "type": "Meter",
                "details": {"type": "bidirectional"},
            },
            "uuid-soc": {
                "name": "Earnie_Batterie_SoC",
                "type": "InfoOnlyAnalog",
                "room": "r1",
                "cat": "c1",
            },
        },
    }
    result = run_greenfield_import(mini, _empty_house())
    plant = result["house_doc"]["plant"]["ehal_bindings"]
    assert plant["sens_ess_soc"] == "Earnie_Batterie_SoC"
    assert plant["sens_grid_power_active"] == "Zähler Netz"
    assert "sens_grid_power_active" in result["report"]["efm_plant_filled"]


def test_normalize_and_save_round_trip(tmp_path, monkeypatch):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    result = run_greenfield_import(_doc(), _empty_house())
    house = result["house_doc"]
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(
        str(path),
        {
            "plant": house.get("plant"),
            "profiles": list(house["profiles"].values()),
        },
    )
    assert path.is_file()
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["profiles"]
    assert any(
        c.get("type") == "ev" for p in reloaded["profiles"] for c in p.get("consumers", [])
    )
    # In-memory normalize also accepts the list form
    normalized = normalize_house_profiles_document(
        {
            "plant": house.get("plant"),
            "profiles": list(house["profiles"].values()),
        }
    )
    assert "waermepumpe" in {
        c["id"] for c in normalized["profiles"]["live"]["consumers"]
    }
