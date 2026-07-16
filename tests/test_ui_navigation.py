"""Tests für die Seiten-Registry der Menüstruktur (Env-/Config-Gating)."""
from __future__ import annotations

from ui.navigation import build_page_specs


def _titles(keys: list[str]) -> list[str]:
    return [spec.title for spec in build_page_specs(keys)]


def test_default_pages_include_core_and_scenario_explorer():
    titles = _titles(["sunset2sunset", "scenario_explorer"])
    assert "Monitor" in titles
    assert "Manuelle Geräte" in titles
    assert "Szenario-Explorer" in titles
    assert "Verbraucheranalyse" in titles
    assert "Live-Konfiguration" in titles
    assert "Loxone-Kommunikation" in titles
    assert "Preis-Prognose (Dev)" not in titles


def test_price_forecast_page_only_when_enabled():
    with_pf = _titles(["sunset2sunset", "scenario_explorer", "price_forecast"])
    assert "Preis-Prognose (Dev)" in with_pf


def test_only_sunset_hides_dev_and_scenario_explorer():
    titles = _titles(["sunset2sunset"])
    assert "Monitor" in titles
    assert "Szenario-Explorer" not in titles
    assert "Preis-Prognose (Dev)" not in titles


def test_cockpit_is_single_default():
    specs = build_page_specs(["sunset2sunset", "scenario_explorer"])
    defaults = [spec for spec in specs if spec.default]
    assert len(defaults) == 1
    assert defaults[0].title == "Monitor"


def test_url_paths_are_unique():
    specs = build_page_specs(["sunset2sunset", "scenario_explorer", "price_forecast"])
    url_paths = [spec.url_path for spec in specs]
    assert len(url_paths) == len(set(url_paths))


def test_sections_are_assigned():
    specs = build_page_specs(["sunset2sunset", "scenario_explorer", "price_forecast"])
    sections = {spec.title: spec.section for spec in specs}
    assert sections["Monitor"] == "Betrieb"
    assert sections["Manuelle Geräte"] == "Betrieb"
    assert sections["Szenario-Explorer"] == "Analyse"
    assert sections["Preis-Prognose (Dev)"] == "Analyse"
    assert sections["Hauskonfigurator"] == "Planung"
    assert sections["Live-Konfiguration"] == "Echtzeit-Umgebung"
    assert sections["Loxone-Kommunikation"] == "Echtzeit-Umgebung"
