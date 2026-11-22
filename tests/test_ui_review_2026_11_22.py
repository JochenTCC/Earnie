"""Fixes of the ``ui/`` code review (2026-11-22)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

_TIMEOUT = 30


# --- Sidebar "Sichern & Übertragen": ZIPs only on request ---------------------------------


def _count_pack_builds(monkeypatch, calls: list[bool]) -> None:
    """Both import paths: ``ui.config_pack`` binds the builder at import time."""
    import ui.config_pack  # noqa: F401 — bind first, then patch both names

    def _build(for_support: bool = False) -> bytes:
        calls.append(for_support)
        return b"PK"

    monkeypatch.setattr("runtime_store.config_pack.build_config_pack_bytes", _build)
    monkeypatch.setattr("ui.config_pack.build_config_pack_bytes", _build)


def _sidebar_app():
    from ui.config_pack import render_backup_transfer_sidebar

    render_backup_transfer_sidebar(expanded=True)


def test_sidebar_builds_no_config_pack_without_a_click(monkeypatch):
    calls: list[bool] = []
    _count_pack_builds(monkeypatch, calls)
    at = AppTest.from_function(_sidebar_app, default_timeout=_TIMEOUT).run()
    assert not at.exception
    assert calls == []
    labels = [b.label for b in at.sidebar.button]
    assert "Konfigurations-ZIP erstellen" in labels
    assert "Konfiguration + Anhänge erstellen" in labels


def test_config_pack_is_built_when_asked(monkeypatch):
    calls: list[bool] = []
    _count_pack_builds(monkeypatch, calls)
    at = AppTest.from_function(_sidebar_app, default_timeout=_TIMEOUT).run()
    button = next(b for b in at.sidebar.button if b.label == "Konfigurations-ZIP erstellen")
    at = button.click().run()
    assert not at.exception
    assert calls == [False]


def test_support_config_pack_is_built_when_asked(monkeypatch):
    calls: list[bool] = []
    _count_pack_builds(monkeypatch, calls)
    at = AppTest.from_function(_sidebar_app, default_timeout=_TIMEOUT).run()
    button = next(
        b for b in at.sidebar.button if b.label == "Konfiguration + Anhänge erstellen"
    )
    at = button.click().run()
    assert not at.exception
    assert calls == [True]


def test_config_pack_import_success_survives_the_rerun(monkeypatch):
    """``st.success`` right before ``st.rerun()`` was never shown; a flash is."""
    import streamlit as st

    from ui import config_pack

    upload = MagicMock()
    upload.getvalue.return_value = b"zip"
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: upload)
    monkeypatch.setattr(st, "button", lambda *a, **k: True)
    monkeypatch.setattr(config_pack, "import_config_pack_bytes", lambda data: ["a", "b"])
    monkeypatch.setattr(config_pack, "_clear_session_after_config_import", lambda: None)
    flashed: list[tuple[str, str]] = []
    monkeypatch.setattr("ui.flash.flash", lambda kind, text: flashed.append((kind, text)))
    monkeypatch.setattr(st.cache_data, "clear", lambda: None)

    class _Rerun(Exception):
        pass

    def _rerun():
        raise _Rerun()

    monkeypatch.setattr(st, "rerun", _rerun)
    with pytest.raises(_Rerun):
        config_pack._render_config_pack_import()
    assert flashed == [("success", "Importiert: 2 Datei(en).")]


# --- Hausprofil: absent-mode read error ------------------------------------------------------


def _absent_status_app():
    from ui.house_config_profile_form import _render_absent_mode_status

    _render_absent_mode_status(profile_absent=False)


def test_absent_mode_read_crash_is_not_readable_not_unbound(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("HA nicht erreichbar")

    monkeypatch.setattr("optimizer.absent_mode.read_ehal_absent_mode", _boom)
    at = AppTest.from_function(_absent_status_app, default_timeout=_TIMEOUT).run()
    assert not at.exception
    text = " ".join(c.value for c in at.caption)
    assert "nicht lesbar" in text
    assert "HA nicht erreichbar" in text
    assert "nicht gebunden" not in text


# --- Scenario: own fixed price has no invented default -------------------------------------


def test_user_fixed_price_blockers():
    from house_config.tariffs_store import USER_FIXED_TARIFF_ID
    from ui.pages.scenario_editor_sections import user_fixed_price_blockers

    assert user_fixed_price_blockers(USER_FIXED_TARIFF_ID, None, None, None) == [
        "Bezugspreis des eigenen Festpreises fehlt"
    ]
    assert user_fixed_price_blockers(
        USER_FIXED_TARIFF_ID, USER_FIXED_TARIFF_ID, 30.0, None
    ) == ["Einspeisevergütung des eigenen Festpreises fehlt"]
    assert user_fixed_price_blockers(USER_FIXED_TARIFF_ID, USER_FIXED_TARIFF_ID, 30.0, 0.0) == []
    assert user_fixed_price_blockers("catalog_tariff", "catalog_export", None, None) == []


def _seed_cents_app():
    import streamlit as st

    import ui.pages.page_scenario_editor  # noqa: F401 — resolves the module cycle first
    from ui.pages.scenario_editor_session import _seed_user_tariff_cent_widgets

    _seed_user_tariff_cent_widgets("scope_x", {})
    st.session_state["seeded"] = True


def test_unsaved_user_prices_start_empty():
    from ui.scenario_form_helpers import scoped_widget_key

    at = AppTest.from_function(_seed_cents_app, default_timeout=_TIMEOUT).run()
    assert not at.exception
    assert at.session_state[scoped_widget_key("scope_x", "scenario_user_import_cent")] is None
    assert at.session_state[scoped_widget_key("scope_x", "scenario_user_export_cent")] is None


# --- Shadow overlay on battery rename ---------------------------------------------------------


def _shadow_overlay(monkeypatch, *, write):
    monkeypatch.setattr("runtime_store.shadow.mode.is_shadow_config_readonly", lambda: True)
    monkeypatch.setattr(
        "runtime_store.shadow.hooks.read_overlay",
        lambda: {"battery_bindings": {"old": {"sens_soc": "x"}}},
    )
    monkeypatch.setattr("runtime_store.shadow.hooks.write_overlay", write)


def test_shadow_overlay_rename_write_failure_is_reported(monkeypatch):
    from ui.house_config_battery_io import _rewrite_shadow_battery_overlay

    def _fail(_doc):
        raise OSError("read-only file system")

    _shadow_overlay(monkeypatch, write=_fail)
    with pytest.raises(ValueError, match="read-only file system"):
        _rewrite_shadow_battery_overlay("old", "new")


def test_shadow_overlay_rename_moves_bindings(monkeypatch):
    from ui.house_config_battery_io import _rewrite_shadow_battery_overlay

    written: list[dict] = []
    _shadow_overlay(monkeypatch, write=written.append)
    _rewrite_shadow_battery_overlay("old", "new")
    assert list(written[0]["battery_bindings"]) == ["new"]


# --- Hausprofil save: grid fee only after the checks -------------------------------------------


def test_rejected_profile_save_writes_no_grid_fee(monkeypatch):
    from ui import house_config_profile_save as save_mod

    persisted: list[str] = []
    monkeypatch.setattr(
        "house_config.own_grid_fee.persist_own_grid_fee",
        lambda netz, **kw: persisted.append(kw["profile_id"]) or netz,
    )

    def _reject(_profile):
        raise ValueError("Bezeichnung bereits vergeben")

    monkeypatch.setattr("ui.house_config_io.check_house_profile", _reject)
    upserts: list[dict] = []
    monkeypatch.setattr(save_mod, "upsert_house_profile", upserts.append)
    monkeypatch.setattr(
        "ui.house_config_historical_csv.historical_csv_save_fields",
        lambda scope, existing: {
            "total_profile_csv": "",
            "pv_profile_csv": "",
            "historical_csv_source": "none",
        },
    )
    monkeypatch.setattr(save_mod, "house_heating_payload", lambda heating: {})
    monkeypatch.setattr(save_mod, "stored_horizon_fields", lambda location: {})
    location = {
        "land": "AT",
        "latitude": 48.0,
        "longitude": 16.0,
        "default_pv_tilt": 30.0,
        "default_pv_azimuth": 180.0,
        "netznutzung": {"area_id": "__own__", "own_base_cent_kwh": 5.0},
    }
    result = save_mod._perform_house_profile_save(
        is_new=True,
        stable_profile_id="",
        label="Haus",
        profile_ids=["haus"],
        annual_kwh=4000.0,
        location=location,
        resolved=[],
        existing={},
        session_scope="new",
        heating={},
        from_auto=True,
    )
    assert result is None
    assert persisted == []
    assert upserts == []
