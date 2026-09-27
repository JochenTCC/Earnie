"""UI-adjacent tests for HA entity-centric EHAL mapping (2.6.h)."""
from __future__ import annotations

import pytest

from integrations.ehal_debug_mapping import (
    expand_ha_telemetry_for_live,
    expand_ha_writes_for_live,
    ha_pattern_b_live_mapping,
)
from integrations.ha_adapter import TELEMETRY_ENERGY_OPTIONAL, TELEMETRY_REQUIRED
from ui import ehal_ha_mapping as ha_map
from ui.ehal_ha_mapping import (
    _NONE,
    _entity_options,
    _field_select_caption,
    _ha_credentials,
    _ha_entity_fields,
    _persist_ha_ess_force,
    _proposed_entity_id,
    _validate_mapping_save,
)
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


def test_ha_consumer_fields_unchanged():
    rows = build_entity_rows(_sample_house(), "live")
    wallbox = next(r for r in rows if r["id"] == "wallbox")
    assert _ha_entity_fields(wallbox) == tuple(wallbox["fields"])
    for name in TELEMETRY_ENERGY_OPTIONAL:
        assert name not in _ha_entity_fields(wallbox)


def test_proposed_entity_id_reads_nested_and_ignores_junk():
    assert _proposed_entity_id({}, "sens_ess_soc") == ""
    assert _proposed_entity_id({"sens_ess_soc": "sensor.x"}, "sens_ess_soc") == ""
    assert (
        _proposed_entity_id(
            {"sens_ess_soc": {"entity_id": " sensor.soc ", "score": 1}},
            "sens_ess_soc",
        )
        == "sensor.soc"
    )


def test_entity_options_dedupes_and_keeps_current():
    rows = [{"entity_id": "sensor.a"}, {"entity_id": ""}, {"entity_id": "sensor.b"}]
    opts = _entity_options(rows, ["sensor.b", "sensor.orphan", ""])
    assert opts[0] == _NONE
    assert opts[1:] == ["sensor.a", "sensor.b", "sensor.orphan"]


def test_field_select_caption_marks_required():
    caption = _field_select_caption("sens_ess_soc", required=True)
    assert "`sens_ess_soc`" in caption
    assert caption.endswith(" *")
    assert not _field_select_caption("sens_ess_soc").endswith(" *")


def test_validate_mapping_save_requires_plant_telemetry():
    err = _validate_mapping_save(PLANT_ENTITY_ID, {"sens_ess_soc": "sensor.soc"})
    assert err is not None and "Pflichtfelder fehlen" in err
    for name in TELEMETRY_REQUIRED:
        if name == "sens_ess_soc":
            continue
        assert name in err
    assert (
        _validate_mapping_save(
            PLANT_ENTITY_ID,
            {name: f"sensor.{name}" for name in TELEMETRY_REQUIRED},
        )
        is None
    )
    assert _validate_mapping_save("wallbox", {}) is None


def test_persist_ha_ess_force_write_and_clear():
    house = {"plant": {"ehal_bindings": {"sens_ess_soc": "sensor.soc"}}}
    with_force = _persist_ha_ess_force(
        house,
        {"driver": "huawei_solar", "device_id": "dev-1", "duration_min": 20},
    )
    assert with_force["plant"]["ha_ess_force"]["device_id"] == "dev-1"
    assert with_force["plant"]["ehal_bindings"]["sens_ess_soc"] == "sensor.soc"
    cleared = _persist_ha_ess_force(with_force, None)
    assert "ha_ess_force" not in cleared["plant"]
    empty = _persist_ha_ess_force({"other": 1}, None)
    assert "plant" not in empty


def test_ha_credentials_reads_sign_and_env(monkeypatch):
    monkeypatch.setattr(
        "runtime_store.dotenv_io.read_ha_credentials",
        lambda: ("http://ha.local:8123", "tok"),
    )
    creds = _ha_credentials(
        {
            "ehal": {
                "backend": "ha",
                "adapter_id": "ha-1",
                "ha": {"sign": {"sens_grid_power_active": "negate"}},
            }
        }
    )
    assert creds["backend"] == "ha"
    assert creds["base_url"] == "http://ha.local:8123"
    assert creds["token"] == "tok"
    assert creds["sign"]["sens_grid_power_active"] == "negate"


def test_adapter_from_form_requires_resolved_credentials(monkeypatch):
    monkeypatch.setattr(
        "integrations.ha_supervisor.resolve_ha_base_url", lambda url: url or None
    )
    monkeypatch.setattr(
        "integrations.ha_supervisor.resolve_ha_token", lambda tok: tok or None
    )
    with pytest.raises(ValueError, match="URL und Token"):
        ha_map._adapter_from_form("", "", {})
    adapter = ha_map._adapter_from_form(
        "http://ha.local:8123", "tok", {"sens_ess_soc": "sensor.soc"}
    )
    assert adapter.cfg.base_url == "http://ha.local:8123"
    assert adapter.cfg.entities["sens_ess_soc"] == "sensor.soc"


def test_clear_map_widget_keys_drops_session_entries(monkeypatch):
    state = {
        "ehal_ha_map_plant_sens_ess_soc": "sensor.soc",
        "ehal_ha_map_plant_other": "x",
        "keep": 1,
    }
    monkeypatch.setattr(ha_map.st, "session_state", state)
    ha_map._clear_map_widget_keys("plant", ("sens_ess_soc", "sens_grid_power_active"))
    assert "ehal_ha_map_plant_sens_ess_soc" not in state
    assert state["keep"] == 1
    assert state["ehal_ha_map_plant_other"] == "x"


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
