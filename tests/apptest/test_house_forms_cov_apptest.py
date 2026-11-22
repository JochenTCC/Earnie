"""Hauskonfigurator setup forms: manual appliances, dynamic EV wallboxes, PV/battery/inverter
defaults and the monthly feed-in rate save path.

Covers helpers no other test executed (full-suite coverage run 2026-11-22). Render helpers
run in AppTest (``from_function``); the isolated config copy comes from
``tests/apptest/conftest.py``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import _reinit_config_offline

_TIMEOUT_S = 30.0


# --- Manual appliance (Earnie role „Manuelles Gerät“) -----------------------------------


def _manual_app(consumer: dict, nominal: float):
    import streamlit as st

    from ui.house_config_profile_generic import _render_generic_manual_fields, _schedule_defaults

    defaults = _schedule_defaults(consumer.get("schedule") or {})
    shift, rec = _render_generic_manual_fields(consumer, 0, nominal, 2.0, defaults, session_scope="cov")
    st.session_state["cov_result"] = {"shift": shift, "rec": rec}


def _manual(consumer: dict, nominal: float = 1.5) -> AppTest:
    at = AppTest.from_function(
        _manual_app, default_timeout=_TIMEOUT_S, kwargs={"consumer": consumer, "nominal": nominal}
    ).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _selectbox(at: AppTest, label: str):
    return next(s for s in at.selectbox if s.label == label)


def _number_input(at: AppTest, label: str):
    return next(n for n in at.number_input if n.label == label)


def test_manual_advice_mode_defaults_without_power_binding():
    at = _manual({"id": "wm", "label": "Waschmaschine"})
    assert _selectbox(at, "Unterstützung").value == "advice"
    assert _number_input(at, "Empfehlungshorizont (h)").value == 12.0
    assert _number_input(at, "Standard-Leistung (kW)").value == 1.5
    assert any(c.value.startswith("Leistungsquelle: Aus Profil (Nennleistung).") for c in at.caption)
    assert not [s for s in at.selectbox if s.label == "Leistungsquelle"]
    assert at.session_state["cov_result"] == {
        "shift": 12.0,
        "rec": {"mode": "advice", "power_source": "manual", "default_power_kw": 1.5},
    }


def test_manual_horizon_and_power_edits_reach_the_result():
    at = _manual({"id": "wm", "label": "Waschmaschine", "schedule": {"start_shift_h": 0.5}})
    # A stored shift below 1 h starts at the default manual horizon.
    assert _number_input(at, "Empfehlungshorizont (h)").value == 6.0
    _number_input(at, "Empfehlungshorizont (h)").set_value(8.5).run()
    _number_input(at, "Standard-Leistung (kW)").set_value(0.0).run()
    assert not at.exception
    result = at.session_state["cov_result"]
    assert result["shift"] == 8.5
    assert result["rec"]["default_power_kw"] == 0.0


def test_manual_stored_zero_power_is_kept():
    at = _manual({"id": "wm", "appliance_recommendation": {"default_power_kw": 0.0}}, nominal=2.0)
    assert _number_input(at, "Standard-Leistung (kW)").value == 0.0


def test_manual_power_source_select_with_sens_power_binding():
    consumer = {
        "id": "wm",
        "appliance_recommendation": {"power_source": "loxone"},
        "ehal_bindings": {"flex.wm.sens_power_act": "sensor.wm_power"},
    }
    at = _manual(consumer)
    source = _selectbox(at, "Leistungsquelle")
    assert source.value == "loxone"
    assert source.options == ["Aus Profil (Nennleistung)", "Smarthome-Binding (EHAL-Com)"]
    assert any("Feld `flex.{id}.sens_power_act`" in c.value for c in at.caption)
    assert at.session_state["cov_result"]["rec"]["power_source"] == "loxone"

    source.set_value("manual").run()
    assert not any("Feld `flex.{id}.sens_power_act`" in c.value for c in at.caption)
    assert at.session_state["cov_result"]["rec"]["power_source"] == "manual"


_POWERSTATIONS = [
    {"id": "house_bat", "label": "Haus", "type": "house"},
    {"id": "ps_virt", "label": "Reserve", "type": "powerstation", "backing": "virtual"},
    {"id": "ps_phys", "label": "Ecoflow", "type": "powerstation", "backing": "physical"},
]


def _reserve_consumer(powerstation_id: str = "") -> dict:
    rec = {"mode": "reserve"}
    if powerstation_id:
        rec["powerstation_id"] = powerstation_id
    return {"id": "wm", "appliance_recommendation": rec}


def test_manual_reserve_without_powerstations_warns(monkeypatch):
    monkeypatch.setattr("ui.house_config_io.list_batteries", lambda: [_POWERSTATIONS[0]])
    at = _manual(_reserve_consumer())
    assert _selectbox(at, "Unterstützung").value == "reserve"
    assert not [n for n in at.number_input if n.label == "Empfehlungshorizont (h)"]
    assert any(w.value.startswith("Keine Powerstation in components.json") for w in at.warning)
    assert _selectbox(at, "Powerstation").options == ["— Powerstation wählen —"]
    rec = at.session_state["cov_result"]["rec"]
    assert rec["mode"] == "reserve"
    assert "powerstation_id" not in rec


def test_manual_reserve_requires_a_powerstation_choice(monkeypatch):
    monkeypatch.setattr("ui.house_config_io.list_batteries", lambda: list(_POWERSTATIONS))
    at = _manual(_reserve_consumer())
    assert _selectbox(at, "Powerstation").options == [
        "— Powerstation wählen —",
        "Reserve (ps_virt)",
        "Ecoflow (ps_phys)",
    ]
    assert [e.value for e in at.error] == ["Modus Energiereserve erfordert eine Powerstation."]

    _selectbox(at, "Powerstation").set_value("ps_virt").run()
    assert not at.error
    assert any(c.value.startswith("Virtuelle Powerstation:") for c in at.caption)
    assert at.session_state["cov_result"]["rec"]["powerstation_id"] == "ps_virt"


def test_manual_reserve_physical_powerstation_has_no_virtual_hint(monkeypatch):
    monkeypatch.setattr("ui.house_config_io.list_batteries", lambda: list(_POWERSTATIONS))
    at = _manual(_reserve_consumer("ps_phys"))
    assert _selectbox(at, "Powerstation").value == "ps_phys"
    assert not any(c.value.startswith("Virtuelle Powerstation:") for c in at.caption)
    assert at.session_state["cov_result"]["rec"]["powerstation_id"] == "ps_phys"


def test_manual_reserve_keeps_unknown_powerstation_visible(monkeypatch):
    monkeypatch.setattr("ui.house_config_io.list_batteries", lambda: list(_POWERSTATIONS))
    at = _manual(_reserve_consumer("ps_gone"))
    box = _selectbox(at, "Powerstation")
    assert box.value == "ps_gone"
    assert box.options[-1] == "ps_gone (fehlt in components.json)"
    assert at.session_state["cov_result"]["rec"]["powerstation_id"] == "ps_gone"


def test_manual_switch_advice_to_reserve(monkeypatch):
    monkeypatch.setattr("ui.house_config_io.list_batteries", lambda: list(_POWERSTATIONS))
    at = _manual({"id": "wm"})
    _selectbox(at, "Unterstützung").set_value("reserve").run()
    assert not at.exception
    assert not [n for n in at.number_input if n.label == "Empfehlungshorizont (h)"]
    assert at.session_state["cov_result"]["rec"]["mode"] == "reserve"


# --- Dynamic EV: allowed wallboxes --------------------------------------------------------


def _wallboxes_app(consumer: dict):
    import streamlit as st

    from ui.house_config_profile_ev import _render_dynamic_wallboxes

    st.session_state["cov_result"] = _render_dynamic_wallboxes(consumer, 0, session_scope="cov")


_WALLBOXES = {
    "lp1": {"id": "lp1", "label": "Garage", "unknown_vehicle": "immediate"},
    "lp2": {"id": "lp2", "label": "Carport", "unknown_vehicle": ""},
}
_DYNAMIC_EV = {
    "id": "car",
    "type": "ev",
    "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["lp1", "lp_gone"]},
}


def _wallboxes(monkeypatch, wallboxes: dict, consumer: dict = _DYNAMIC_EV) -> AppTest:
    monkeypatch.setattr("ui.house_config_wallbox_io.wallboxes_map", lambda: dict(wallboxes))
    at = AppTest.from_function(_wallboxes_app, default_timeout=_TIMEOUT_S, kwargs={"consumer": consumer}).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_dynamic_wallboxes_none_defined_warns(monkeypatch):
    at = _wallboxes(monkeypatch, {})
    assert [w.value for w in at.warning] == ["Noch keine Wallbox angelegt (Tab „Wallboxen“)."]
    assert not at.multiselect
    assert at.session_state["cov_result"] == []


def test_dynamic_wallboxes_seeded_from_consumer_without_unknown_ids(monkeypatch):
    at = _wallboxes(monkeypatch, _WALLBOXES)
    [box] = at.multiselect
    assert box.label == "Erlaubte Wallboxen"
    assert box.options == ["Garage", "Carport"]
    assert box.value == ["lp1"]
    assert at.session_state["cov_result"] == ["lp1"]
    assert not at.warning
    assert any(c.value.startswith("Geplant wird das Auto erst") for c in at.caption)


def test_dynamic_wallboxes_warn_on_missing_unknown_vehicle_and_empty_choice(monkeypatch):
    at = _wallboxes(monkeypatch, _WALLBOXES)
    at.multiselect[0].set_value(["lp1", "lp2"]).run()
    assert at.session_state["cov_result"] == ["lp1", "lp2"]
    assert [w.value for w in at.warning] == ["Für Carport fehlt „Unbekanntes Auto“ (Tab „Wallboxen“)."]

    at.multiselect[0].set_value([]).run()
    assert at.session_state["cov_result"] == []
    assert [w.value for w in at.warning] == [
        "Mindestens eine Wallbox wählen — sonst wird das Hausprofil nicht gespeichert."
    ]


def test_dynamic_wallboxes_drop_a_deleted_wallbox_from_the_session(monkeypatch):
    at = _wallboxes(monkeypatch, _WALLBOXES)
    at.multiselect[0].set_value(["lp1", "lp2"]).run()
    monkeypatch.setattr("ui.house_config_wallbox_io.wallboxes_map", lambda: {"lp1": _WALLBOXES["lp1"]})
    at.run()
    assert not at.exception
    assert at.session_state["cov_result"] == ["lp1"]


# --- PV-Felder: defaults from the house profile for a new PV field ----------------------


def _pv_tab_app():
    from ui.planning_pv_form import render_pv_planning_tab

    render_pv_planning_tab()


def _edit_json(env: str, change) -> None:
    path = Path(os.environ[env])
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _add_profile(doc: dict) -> None:
    base = doc["profiles"][0]
    doc["profiles"].append(
        {**base, "id": "nordhang", "label": "Nordhang", "default_pv_tilt": 40, "default_pv_azimuth": -30}
    )


def _new_pv_field(monkeypatch) -> AppTest:
    """Open „— neu —“ with no field to clone (no template source, no Live PV field).

    ``auto_persist`` is stubbed: the new-field draft would otherwise save itself on the
    first run and the page would jump to the saved field (see the xfail test below).
    """
    monkeypatch.setattr("ui.planning_pv_form.get_live_scenario_refs", lambda: {"house_profile_id": "test_home"})
    monkeypatch.setattr("ui.planning_pv_form.auto_persist", lambda **kwargs: False)
    at = AppTest.from_function(_pv_tab_app, default_timeout=_TIMEOUT_S).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="planning_pv_select").value == "— neu —"
    return at


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug: with no Live PV field the PV tab opens on „— neu —“ and auto_persist saves the "
        "seeded draft („Dach Süd“) on the first render — opening the tab writes components.json "
        "(same class as the fixed house-profile / inverter „— neu —“ bugs)."
    ),
)
def test_opening_pv_tab_without_live_pv_field_writes_nothing(monkeypatch):
    monkeypatch.setattr(
        "ui.planning_pv_form.get_live_scenario_refs", lambda: {"house_profile_id": "test_home", "pv_system_ids": []}
    )
    path = Path(os.environ["EARNIE_COMPONENTS_PATH"])
    before = path.read_bytes()
    at = AppTest.from_function(_pv_tab_app, default_timeout=_TIMEOUT_S).run()
    assert not at.exception
    assert path.read_bytes() == before


def test_new_pv_field_shows_profile_defaults_caption(monkeypatch):
    at = _new_pv_field(monkeypatch)
    box = _selectbox(at, "Defaults aus Hausprofil")
    assert box.options == ["Test-Haushalt 4000 kWh/a"]
    assert any(
        c.value == "Vorschlag Neigung/Azimut aus Profil (25° / 0°) — im Formular überschreibbar."
        for c in at.caption
    ), [c.value for c in at.caption]


def test_new_pv_field_profile_pick_applies_tilt_and_azimuth(monkeypatch):
    _edit_json("EARNIE_HOUSE_PROFILES_PATH", _add_profile)
    _reinit_config_offline()
    at = _new_pv_field(monkeypatch)
    _selectbox(at, "Defaults aus Hausprofil").set_value("Nordhang").run()
    assert not at.exception
    assert any("(40° / -30°)" in c.value for c in at.caption)
    assert _number_input(at, "Dachneigung (°)").value == 40.0


def _pv_defaults_app(seed: str):
    import streamlit as st

    from ui.house_config_io import load_house_profiles
    from ui.planning_pv_form import _render_pv_profile_defaults

    if "cov_seeded" not in st.session_state:
        st.session_state["cov_seeded"] = True
        st.session_state["cov__planning_pv_defaults_profile"] = seed
    _render_pv_profile_defaults("cov", load_house_profiles().get("profiles", {}))


def test_pv_profile_defaults_map_a_legacy_profile_id_in_session():
    at = AppTest.from_function(_pv_defaults_app, default_timeout=_TIMEOUT_S, kwargs={"seed": "test_home"}).run()
    assert not at.exception, [e.value for e in at.exception]
    # Older sessions held the profile id; the select shows the Bezeichnung.
    assert at.selectbox(key="cov__planning_pv_defaults_profile").value == "Test-Haushalt 4000 kWh/a"
    assert any("(25° / 0°)" in c.value for c in at.caption)


# --- Battery / inverter templates ---------------------------------------------------------


def test_battery_seed_defaults_for_a_new_battery():
    from ui.planning_battery_state import _battery_seed_defaults

    seed = _battery_seed_defaults()
    assert seed["label"] == "5 kWh Speicher"
    assert (seed["capacity"], seed["max_charge"], seed["max_discharge"]) == (5.0, 2.5, 2.5)
    assert (seed["min_soc"], seed["max_soc"], seed["threshold_percent"]) == (10.0, 100.0, 5.0)
    assert (seed["bat_type"], seed["backing"], seed["role"]) == ("house", "virtual", "single_use")
    assert seed["inverter_id"] == "wr_main"  # the only inverter of the fixture
    assert seed["wear_enabled"] is False


def test_battery_seed_defaults_label_stays_unique(monkeypatch):
    from ui import planning_battery_state

    monkeypatch.setattr(planning_battery_state, "list_batteries", lambda: [{"id": "b", "label": "5 kWh Speicher"}])
    assert planning_battery_state._battery_seed_defaults()["label"] != "5 kWh Speicher"


def test_new_inverter_template_without_source_is_empty_hybrid():
    from house_config.inverter import DEFAULT_AC_CONNECTION, DEFAULT_INVERTER_TYPE
    from ui.planning_inverter_form import new_inverter_template

    template = new_inverter_template([{"id": "x", "label": "Haupt-Wechselrichter"}], source_id="missing")
    assert template["type"] == DEFAULT_INVERTER_TYPE
    assert template["ac_connection"] == DEFAULT_AC_CONNECTION
    assert template["label"] != "Haupt-Wechselrichter"
    assert set(template) == {"label", "type", "ac_connection", "control"}
    assert new_inverter_template([])["label"] == "Haupt-Wechselrichter"


def test_new_inverter_template_clones_source_without_bindings():
    from ui.planning_inverter_form import new_inverter_template

    source = {
        "id": "wr1",
        "label": "Dach",
        "type": "PV_String",
        "ac_connection": "Island",
        "control": "Full",
        "efficiency": "",
        "max_ac_power_kw": "8",
        "max_pv_input_kw": None,
        "max_ac_charge_kw": 3,
        "ehal_bindings": {"inv.wr1.sens_inv_power_pv": "sensor.pv"},
    }
    template = new_inverter_template([source, "not-a-dict"], source_id=" wr1 ")
    from house_config.inverter import DEFAULT_INVERTER_EFFICIENCY

    assert template == {
        "label": "Dach copy",
        "type": "pv_string",
        "ac_connection": "island",
        "control": "full",
        "efficiency": DEFAULT_INVERTER_EFFICIENCY,
        "ehal_bindings": {},
        "max_ac_power_kw": 8.0,
        "max_ac_charge_kw": 3.0,
    }


# --- Monthly feed-in rate -----------------------------------------------------------------


def test_append_tariff_monthly_rate_writes_row_and_reloads_config(monkeypatch):
    import config
    from ui.house_config_io import append_tariff_monthly_rate

    reloads: list[int] = []
    real_reload = config.reload_config
    monkeypatch.setattr(config, "reload_config", lambda *a, **k: (reloads.append(1), real_reload(*a, **k))[1])
    append_tariff_monthly_rate(side="export", tariff_id="monthly_test", year=2027, month=2, tariff_cent_kwh=6.5)
    append_tariff_monthly_rate(side="export", tariff_id="monthly_test", year=2025, month=1, tariff_cent_kwh=9.5)
    doc = json.loads(Path(os.environ["EARNIE_TARIFFS_PATH"]).read_text(encoding="utf-8"))
    rates = next(t for t in doc["export_tariffs"] if t["id"] == "monthly_test")["monthly_rates"]
    assert {"year": 2027, "month": 2, "tariff_cent_kwh": 6.5} in rates
    jan = [r for r in rates if (r["year"], r["month"]) == (2025, 1)]
    assert jan == [{"year": 2025, "month": 1, "tariff_cent_kwh": 9.5}]  # replaced, not duplicated
    assert reloads == [1, 1]


def test_append_tariff_monthly_rate_rejects_non_monthly_tariff():
    from ui.house_config_io import append_tariff_monthly_rate

    path = Path(os.environ["EARNIE_TARIFFS_PATH"])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        append_tariff_monthly_rate(side="export", tariff_id="fixed_37ct", year=2027, month=2, tariff_cent_kwh=6.5)
    assert path.read_bytes() == before
