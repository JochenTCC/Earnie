"""EHAL-Com live read / Schreibtest regressions (ui/ review slice 1b)."""
from __future__ import annotations

import pytest

from integrations import ehal_write_test_bounds as bounds
from integrations.ha_adapter_core import HaHttpError
from integrations.loxone_connectivity_base import LoxoneCheck
from runtime_store.ehal_push_inbox import STATE_ZERO_ASSUMED_NEVER
from ui import ehal_write_test as ewt_ui


@pytest.fixture
def session(monkeypatch) -> dict:
    state: dict = {}
    monkeypatch.setattr(ewt_ui.st, "session_state", state)
    return state


# --- Schreibtest dialog ------------------------------------------------------------


def test_dismissing_the_confirm_dialog_drops_the_queued_write(session):
    ewt_ui._queue_action("manual", values={"set_ess_mode": 1}, force=False, wait_s=1.0)
    session[ewt_ui._SESSION_PENDING]["force_confirmed"] = True
    ewt_ui._discard_pending()
    assert ewt_ui._SESSION_PENDING not in session


def test_wait_zero_is_kept(session, monkeypatch):
    seen: dict = {}

    def fake_roundtrip(values, **kw):
        seen["wait_s"] = kw["wait_s"]
        raise RuntimeError("stop")

    monkeypatch.setattr(ewt_ui, "roundtrip_batch", fake_roundtrip)
    monkeypatch.setattr(ewt_ui, "default_ev_nominal_a", lambda: None)
    monkeypatch.setattr(ewt_ui.config, "get_battery_params", lambda: {"max_power_kw": 5.0})
    ewt_ui._queue_action("roundtrip", values={"set_ess_mode": 1}, force=False, wait_s=0.0)
    ewt_ui._execute_pending()
    assert seen["wait_s"] == 0.0


def test_hub_http_error_becomes_a_result_not_a_traceback(session, monkeypatch):
    def failing_write(values, **kw):
        raise HaHttpError("HA 502 Bad Gateway")

    monkeypatch.setattr(ewt_ui, "write_probes", failing_write)
    monkeypatch.setattr(ewt_ui, "default_ev_nominal_a", lambda: None)
    monkeypatch.setattr(ewt_ui.config, "get_battery_params", lambda: {"max_power_kw": 5.0})
    ewt_ui._queue_action("manual", values={"set_ess_mode": 1}, force=False, wait_s=1.0)
    ewt_ui._execute_pending()
    result = session[ewt_ui._SESSION_RESULT]
    assert result["kind"] == "error"
    assert "502" in result["message"]


def test_unit_note_names_unit_and_bound_source(monkeypatch):
    monkeypatch.setattr(bounds, "limit_power_bound_kw", lambda f, d: (3.0, "Batterie b2"))
    monkeypatch.setattr(ewt_ui, "limit_power_bound_kw", lambda f, d: (3.0, "Batterie b2"))
    field = "ess.b2.set_ess_charge_power_limit"
    note = ewt_ui._unit_note(field, max_power_kw=5.0, kind=bounds.probe_kind(field))
    assert note == "W · max aus Batterie b2"
    assert ewt_ui._unit_note("x", max_power_kw=5.0, kind="set_evcs_max_current") == "A"


# --- per-entity power bound ---------------------------------------------------------


@pytest.fixture
def entities(monkeypatch):
    import config

    monkeypatch.setattr(
        config,
        "get_battery_params_list",
        lambda: [{"id": "house", "max_power_kw": 5.0}, {"id": "station", "max_power_kw": 0.8}],
    )
    monkeypatch.setattr(
        config,
        "get_inverters",
        lambda: [{"id": "wr_main", "max_ac_power_kw": 10.0}, {"id": "wr_small"}],
    )


def test_battery_limit_uses_its_own_battery(entities):
    assert bounds.limit_power_bound_kw("ess.station.set_ess_charge_power_limit", 5.0) == (
        0.8,
        "Batterie station",
    )
    lo, hi, unit = bounds.probe_value_bounds(
        "ess.station.set_ess_discharge_power_limit", max_power_kw=5.0
    )
    assert (lo, hi, unit) == (0.0, 800.0, "W")
    with pytest.raises(bounds.WriteTestClampError):
        bounds.clamp_probe_value(
            "ess.station.set_ess_charge_power_limit", 1000.0, max_power_kw=5.0
        )


def test_inverter_limit_uses_the_inverter(entities):
    assert bounds.limit_power_bound_kw("inv.wr_main.set_inv_ac_power_limit", 5.0) == (
        10.0,
        "Wechselrichter wr_main",
    )
    assert bounds.clamp_probe_value(
        "inv.wr_main.set_inv_ac_power_limit", 8000.0, max_power_kw=5.0
    ) == pytest.approx(8000.0)


def test_entity_without_own_maximum_says_where_the_bound_comes_from(entities):
    assert bounds.limit_power_bound_kw("inv.wr_small.set_inv_ac_power_limit", 5.0) == (
        5.0,
        "Live-Batterie",
    )
    # flat key with two inverters: no unique inverter
    assert bounds.limit_power_bound_kw("set_inv_ac_power_limit", 5.0) == (5.0, "Live-Batterie")
    assert bounds.limit_power_bound_kw("set_ess_charge_power_limit", 5.0) == (
        5.0,
        "Live-Batterie",
    )


# --- HA YAML package ----------------------------------------------------------------


def test_carrier_package_fails_loud_on_unreadable_components(monkeypatch):
    from ui import ha_carrier_download
    import ui.house_config_io as hcio

    monkeypatch.setattr(hcio, "load_house_profiles", lambda: {"profiles": {}})

    def broken():
        raise ValueError("components.json kaputt")

    monkeypatch.setattr(hcio, "_load_components_document", broken)
    with pytest.raises(ValueError, match="kaputt"):
        ha_carrier_download._load_docs()


# --- Live-Lesen ---------------------------------------------------------------------


def test_never_received_is_coloured_as_stale():
    from ui.ehal_live_read_style import _COLOR_STALE, live_read_text_color

    assert live_read_text_color("nie empfangen", optional=False) == _COLOR_STALE
    assert live_read_text_color("nie empfangen", optional=True) == _COLOR_STALE


def test_zero_assumed_never_shows_the_assumed_zero(monkeypatch):
    import ui.loxone_debug  # noqa: F401 — loads loxone_debug_rows in the app's import order
    from ui import loxone_debug_rows
    from ui.ehal_live_read_style import apply_optional_fallback_hint

    monkeypatch.setattr(loxone_debug_rows, "_inbox_last_read_local", lambda _eid: "")
    item = LoxoneCheck(
        "sens_pv_energy",
        "sens_pv_energy",
        False,
        f"Wert=0; {STATE_ZERO_ASSUMED_NEVER} — Signalliste → Export",
        severity="warning",
        state=STATE_ZERO_ASSUMED_NEVER,
    )
    row = loxone_debug_rows._read_row_from_check(
        "sens_pv_energy", item, mapping="sens_pv_energy", read_at="12:00:00"
    )
    assert row["Wert"].startswith("0")
    assert row["Status"] == STATE_ZERO_ASSUMED_NEVER
    hinted = apply_optional_fallback_hint(row)
    assert "config defaults" not in hinted["Detail"]


# --- OpenEMS ------------------------------------------------------------------------


def test_openems_empty_credentials_are_rejected_not_defaulted():
    from ui.ehal_connection import openems_form_error

    base = {"base_url": "http://edge:8084", "username": "x", "password": "admin"}
    assert openems_form_error(base) is None
    assert "Base-URL" in openems_form_error({**base, "base_url": ""})
    assert "Benutzername und Passwort" in openems_form_error({**base, "username": ""})
    assert "Benutzername und Passwort" in openems_form_error({**base, "password": ""})
