"""AppTest: app.py shell paths no other test reached (coverage gap, 2026-11-22).

Config error page, downgrade / config drift / Loxone auth warnings above the pages,
first-run EHAL setup gate.
The page navigation is replaced by a stub so only the shell renders.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_ROOT = Path(__file__).resolve().parents[2]
_APP = _ROOT / "app.py"
_TIMEOUT = 60


class _NoNavigation:
    def run(self) -> None:
        st.markdown("STUB-PAGE")


@pytest.fixture
def shell(monkeypatch):
    """Past the EHAL gate, navigation stubbed; banners return nothing unless a test sets them."""
    from runtime_store import config_drift, dotenv_io, version_track
    from ui import loxone_auth_banner, navigation

    monkeypatch.setattr(dotenv_io, "needs_loxone_setup", lambda: False)
    monkeypatch.setattr(dotenv_io, "require_loxone_credentials_for_config", lambda: False)
    monkeypatch.setattr(navigation, "build_navigation", lambda _keys: _NoNavigation())
    monkeypatch.setattr(version_track, "consume_downgrade_warning", lambda: None)
    monkeypatch.setattr(config_drift, "should_show_config_drift", lambda: False)
    monkeypatch.setattr(loxone_auth_banner, "render_loxone_auth_error_banner", lambda: None)
    return monkeypatch


def _run_app() -> AppTest:
    at = AppTest.from_file(str(_APP), default_timeout=_TIMEOUT).run()
    assert_clean(at)
    return at


def _warnings(at: AppTest) -> list[str]:
    return [w.value for w in at.main.warning]


def test_config_error_page_explains_and_offers_pack_import(monkeypatch):
    from runtime_store import config_load

    monkeypatch.setattr(config_load, "load_config_for_ui", lambda: (None, "config.json: Zeile 3 kaputt"))
    at = _run_app()
    assert [e.value for e in at.error] == [
        "Die Konfiguration kann nicht geladen werden:\n\nconfig.json: Zeile 3 kaputt"
    ]
    assert "Sichern & Übertragen" in at.info[0].value
    assert any(e.label == "Sichern & Übertragen" for e in at.sidebar.expander)
    assert not any(m.value == "STUB-PAGE" for m in at.markdown)


def test_shell_without_notices_shows_only_the_page(shell):
    at = _run_app()
    assert any(m.value == "STUB-PAGE" for m in at.markdown)
    assert not any("Downgrade" in w or "Drift" in w for w in _warnings(at))


def test_downgrade_warning_is_shown(shell):
    from runtime_store import version_track

    shell.setattr(version_track, "consume_downgrade_warning", lambda: "Downgrade von 2.8 auf 2.7 erkannt")
    at = _run_app()
    assert "Downgrade von 2.8 auf 2.7 erkannt" in _warnings(at)


def test_drift_warning_lists_items(shell):
    from runtime_store import config_drift

    shell.setattr(config_drift, "should_show_config_drift", lambda: True)
    shell.setattr(config_drift, "load_config_drift_items", lambda: ["tariffs.json"])
    shell.setattr(config_drift, "format_drift_message", lambda items: f"Drift: {', '.join(items)}")
    at = _run_app()
    assert "Drift: tariffs.json" in _warnings(at)


@pytest.mark.parametrize("items", [[], FileNotFoundError("no snapshot")], ids=["no-items", "no-snapshot"])
def test_drift_warning_silent_without_items(shell, items):
    from runtime_store import config_drift

    def _load():
        if isinstance(items, Exception):
            raise items
        return items

    shell.setattr(config_drift, "should_show_config_drift", lambda: True)
    shell.setattr(config_drift, "load_config_drift_items", _load)
    shell.setattr(config_drift, "format_drift_message", lambda _i: "Drift: SHOULD NOT SHOW")
    at = _run_app()
    assert "Drift: SHOULD NOT SHOW" not in _warnings(at)
    assert any(m.value == "STUB-PAGE" for m in at.markdown)


def test_loxone_auth_banner_is_rendered(shell):
    from ui import loxone_auth_banner

    shell.setattr(loxone_auth_banner, "render_loxone_auth_error_banner", lambda: st.error("LOXONE-AUTH"))
    at = _run_app()
    assert "LOXONE-AUTH" in [e.value for e in at.error]


def test_ehal_gate_shows_setup_page_and_stops(shell):
    from runtime_store import dotenv_io
    from ui.pages import page_smarthome_backend

    shell.setattr(dotenv_io, "needs_loxone_setup", lambda: True)
    shell.setattr(page_smarthome_backend, "render", lambda: st.markdown("SB-SETUP"))
    at = _run_app()
    markdown = [m.value for m in at.markdown]
    assert "SB-SETUP" in markdown
    assert "STUB-PAGE" not in markdown
    assert any(c.value.startswith("Version ") for c in at.main.caption)
    assert any(e.label == "Info / About" for e in at.sidebar.expander)


