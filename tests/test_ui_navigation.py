"""Tests für die Seiten-Registry der Menüstruktur (Env-/Config-Gating)."""
from __future__ import annotations

from unittest.mock import MagicMock

from ui.navigation import build_page_specs, wrap_offline_stub

_FULL_MODES = ["sunset2sunset", "scenario_explorer", "live_environment"]


def _titles(keys: list[str]) -> list[str]:
    return [spec.title for spec in build_page_specs(keys)]


def test_default_pages_include_core_and_scenario_explorer():
    titles = _titles(_FULL_MODES)
    assert "Monitor" in titles
    assert "Manuelle Geräte" in titles
    assert "Szenario-Explorer" in titles
    assert "Verbraucheranalyse" in titles
    assert "Live-Konfiguration" in titles
    assert "Loxone-Kommunikation" in titles
    assert "Preis-Prognose (Dev)" not in titles


def test_price_forecast_page_only_when_enabled():
    with_pf = _titles([*_FULL_MODES, "price_forecast"])
    assert "Preis-Prognose (Dev)" in with_pf


def test_only_sunset_hides_dev_and_scenario_explorer():
    titles = _titles(["sunset2sunset", "live_environment"])
    assert "Monitor" in titles
    assert "Live-Konfiguration" in titles
    assert "Verbraucheranalyse" in titles
    assert "Szenario-Explorer" not in titles
    assert "Preis-Prognose (Dev)" not in titles


def test_scenario_explorer_only_hides_betrieb_and_echtzeit():
    titles = _titles(["scenario_explorer"])
    assert "Monitor" not in titles
    assert "Manuelle Geräte" not in titles
    assert "Verbraucheranalyse" not in titles
    assert "Live-Konfiguration" not in titles
    assert "Optimierer-Dienst" not in titles
    assert "Loxone-Kommunikation" not in titles
    assert "Szenario-Explorer" in titles
    assert "Hauskonfigurator" in titles
    defaults = [spec for spec in build_page_specs(["scenario_explorer"]) if spec.default]
    assert len(defaults) == 1
    assert defaults[0].title == "Szenario-Explorer"


def test_verbraucheranalyse_hidden_without_live_environment():
    titles = _titles(["sunset2sunset", "scenario_explorer"])
    assert "Monitor" in titles
    assert "Verbraucheranalyse" not in titles
    assert "Live-Konfiguration" not in titles


def test_cockpit_is_single_default():
    specs = build_page_specs(_FULL_MODES)
    defaults = [spec for spec in specs if spec.default]
    assert len(defaults) == 1
    assert defaults[0].title == "Monitor"


def test_url_paths_are_unique():
    specs = build_page_specs([*_FULL_MODES, "price_forecast"])
    url_paths = [spec.url_path for spec in specs]
    assert len(url_paths) == len(set(url_paths))


def test_sections_are_assigned():
    specs = build_page_specs([*_FULL_MODES, "price_forecast"])
    sections = {spec.title: spec.section for spec in specs}
    assert sections["Monitor"] == "Live-Cockpit"
    assert sections["Manuelle Geräte"] == "Live-Cockpit"
    assert sections["Verbraucheranalyse"] == "Live-Cockpit"
    assert sections["Preis-Prognose (Dev)"] == "Live-Cockpit"
    assert sections["Szenario-Explorer"] == "Konfiguration"
    assert sections["Hauskonfigurator"] == "Konfiguration"
    assert sections["Live-Konfiguration"] == "Konfiguration"
    assert sections["Loxone-Kommunikation"] == "Daemon Control"
    assert "Analyse" not in {s.section for s in specs}
    assert "Planung" not in {s.section for s in specs}
    assert "Betrieb" not in {s.section for s in specs}


def test_betrieb_order_price_forecast_after_verbraucheranalyse():
    specs = build_page_specs([*_FULL_MODES, "price_forecast"])
    betrieb = [s.title for s in specs if s.section == "Live-Cockpit"]
    assert betrieb.index("Verbraucheranalyse") < betrieb.index("Preis-Prognose (Dev)")


def test_konfiguration_order_explorer_before_live_konfig():
    specs = build_page_specs(_FULL_MODES)
    konfig = [s.title for s in specs if s.section == "Konfiguration"]
    assert konfig[-1] == "Live-Konfiguration"
    assert konfig.index("Szenario-Explorer") < konfig.index("Live-Konfiguration")


def test_wrap_offline_stub_shows_notice(monkeypatch):
    calls: list[str] = []

    def _render() -> None:
        calls.append("render")

    fake_st = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_st)
    wrapped = wrap_offline_stub(
        _render,
        "offline-notice",
        is_offline=lambda: True,
    )
    wrapped()
    fake_st.warning.assert_called_once_with("offline-notice")
    assert calls == []


def test_wrap_offline_stub_calls_render_when_online():
    calls: list[str] = []

    def _render() -> None:
        calls.append("render")

    wrapped = wrap_offline_stub(
        _render,
        "offline-notice",
        is_offline=lambda: False,
    )
    wrapped()
    assert calls == ["render"]
