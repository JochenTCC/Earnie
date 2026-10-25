"""AppTest-Smoketests für den Hauskonfigurator (echtes Rendering, headless).

AppTest.from_function() führt nur den Funktions-Body ohne Modul-Imports aus
(NameError auf importierte Namen) — daher zeigt jedes Test-Skript unter
tests/apptest/scripts/ per from_file() auf die echte render()-Funktion.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
# Battery/PV forms grew (entity-id lock, readiness); default 3s flakes under xdist.
_TIMEOUT_S = 10.0


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not at.exception


def test_title_and_default_tab():
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert at.title[0].value == "🏠 Hauskonfigurator"
    [tabs] = at.segmented_control
    assert tabs.options == [
        "Hausprofil",
        "Wechselrichter",
        "PV-Felder",
        "Batterien",
    ]
    assert tabs.value == "Hausprofil"


def test_loxone_import_moved_to_smarthome_backend_page():
    """Loxone-Import now lives on Smarthome-Backend, not Hausprofil (see M4)."""
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not any("Loxone-Import" in h.value for h in at.subheader)


def test_switch_to_pv_tab_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    [tabs] = at.segmented_control
    tabs.set_value("PV-Felder").run(timeout=_TIMEOUT_S)
    assert not at.exception
    [tabs_after] = at.segmented_control
    assert tabs_after.value == "PV-Felder"


def test_switch_to_batterien_tab_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    [tabs] = at.segmented_control
    tabs.set_value("Batterien").run(timeout=_TIMEOUT_S)
    assert not at.exception


def test_switch_to_wechselrichter_tab_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    [tabs] = at.segmented_control
    tabs.set_value("Wechselrichter").run(timeout=_TIMEOUT_S)
    assert not at.exception
    [tabs_after] = at.segmented_control
    assert tabs_after.value == "Wechselrichter"


def test_climate_fetch_over_budget_shows_error_instead_of_hanging(monkeypatch, tmp_path):
    from data import open_meteo_solar_archive as archive
    from optimizer.thermal_year_cache import clear_year_model_caches

    def too_slow(**_kwargs):
        raise archive.ClimateFetchBudgetExceeded("Open-Meteo-Klimadaten: Budget überschritten.")

    monkeypatch.setattr(archive, "_fetch_hourly_archive_chunk", too_slow)
    monkeypatch.setattr(archive, "OPEN_METEO_CACHE_DIR", tmp_path / "cold_cache")
    archive.clear_open_meteo_bundle_mem_cache()
    clear_year_model_caches()
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert any("Budget überschritten" in err.value for err in at.error)
