"""Profiling harness for the Hauskonfigurator page (not collected by the suite).

Runs the real page through ``AppTest`` (same offline isolation as the AppTests,
``tests/apptest/conftest.py``) and profiles every script run inside the script
thread with pyinstrument. Scenarios: cold open, warm rerun, three field edits,
tab switches — for the test fixture profile and for the richer example profile
(heat pump + EV + three appliances, ``share/config/house_profiles.example.json``).

Run (needs ``pip install pyinstrument``; the file name is not a ``test_*`` pattern,
so pass it explicitly):

    PROFILE_OUT=/tmp/hk-prof python -m pytest tests/apptest/perf_house_config_harness.py -q -n 0

Output in ``$PROFILE_OUT``: ``timings.txt`` (wall time per run), ``*.tree.txt`` /
``*.html`` (pyinstrument call trees) and ``cache_keys.txt`` (year-model cache
hits / misses). Results and findings: ``docs/dev/hk-page-profiling.md``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytest.importorskip("pyinstrument")

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
OUT = Path(os.environ.get("PROFILE_OUT", "/tmp/hk-prof"))
ROOT = Path(__file__).resolve().parents[2]


_CURRENT = {"label": "", "n": 0}


def _install_render_profiler(monkeypatch):
    """Profile inside the script thread: wrap page render() with pyinstrument."""
    from pyinstrument import Profiler
    from ui.pages import page_house_config

    real = page_house_config.render

    def wrapped():
        prof = Profiler(interval=0.002, async_mode="disabled")
        t0 = time.perf_counter()
        prof.start()
        try:
            real()
        finally:
            prof.stop()
            dt = time.perf_counter() - t0
            _CURRENT["n"] += 1
            label = f"{_CURRENT['label']}_run{_CURRENT['n']}"
            (OUT / f"{label}.tree.txt").write_text(
                prof.output_text(unicode=True, color=False, show_all=False), encoding="utf-8")
            (OUT / f"{label}.html").write_text(prof.output_html(), encoding="utf-8")
            with open(OUT / "timings.txt", "a", encoding="utf-8") as fh:
                fh.write(f"    {label}: render {dt:.3f}s\n")

    monkeypatch.setattr(page_house_config, "render", wrapped)
    from optimizer import thermal_year_cache as tyc

    real_goc = tyc.YearModelCache.get_or_compute

    def logged(self, key, compute, copy):
        hit = key in self._entries
        with open(OUT / "cache_keys.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{_CURRENT['label']}_run{_CURRENT['n']+1} {self.name} {'HIT ' if hit else 'MISS'} {_short(key)}\n")
        return real_goc(self, key, compute, copy)

    monkeypatch.setattr(tyc.YearModelCache, "get_or_compute", logged)


def _short(key, depth=0):
    if os.environ.get("PROFILE_FULL_KEYS"):
        return repr(key)
    if isinstance(key, tuple):
        return "(" + ", ".join(_short(k, depth + 1) for k in key) + ")"
    s = repr(key)
    return s if len(s) <= 90 else s[:40] + "…" + s[-30:]


def _profile(label: str, fn):
    _CURRENT["label"] = label
    _CURRENT["n"] = 0
    t0 = time.perf_counter()
    fn()
    dt = time.perf_counter() - t0
    with open(OUT / "timings.txt", "a", encoding="utf-8") as fh:
        fh.write(f"{label}: {dt:.3f}s\n")
    return dt


def _use_example_profile(monkeypatch):
    """Swap the fixture profile for share/config/house_profiles.example.json (WP + EV + 3 generic)."""
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    doc = json.loads((ROOT / "share/config/house_profiles.example.json").read_text("utf-8"))
    fixture = json.loads(path.read_text("utf-8"))
    # keep fixture netznutzung (user_test_home) so grid-fee resolution works offline
    for p in doc["profiles"]:
        p["netznutzung"] = fixture["profiles"][0].get("netznutzung")
        p["id"] = "test_home"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
    comp_path = Path(os.environ["EARNIE_COMPONENTS_PATH"])
    comp = json.loads(comp_path.read_text("utf-8"))
    ex = json.loads((ROOT / "share/config/components.example.json").read_text("utf-8"))
    comp["heating_systems"] = ex.get("heating_systems", [])
    comp_path.write_text(json.dumps(comp, ensure_ascii=False, indent=2), "utf-8")


@pytest.mark.parametrize("variant", ["fixture", "example"])
def test_profile_house_config(monkeypatch, variant):
    OUT.mkdir(parents=True, exist_ok=True)
    if variant == "example":
        _use_example_profile(monkeypatch)
    from optimizer.thermal_year_cache import clear_year_model_caches
    from data.open_meteo_solar_archive import clear_open_meteo_bundle_mem_cache
    clear_year_model_caches()
    clear_open_meteo_bundle_mem_cache()

    _install_render_profiler(monkeypatch)
    at = AppTest.from_file(str(_SCRIPT), default_timeout=120)
    _profile(f"{variant}_01_cold", lambda: at.run())
    assert not at.exception, at.exception
    _profile(f"{variant}_02_warm_rerun", lambda: at.run())
    assert not at.exception
    # widget change: Jahresverbrauch +100
    ni = [w for w in at.number_input if "annual_kwh" in (w.key or "")]
    assert ni, [w.key for w in at.number_input]
    ni[0].set_value(float(ni[0].value) + 100.0)
    _profile(f"{variant}_03_edit_annual_kwh", lambda: at.run())
    assert not at.exception
    # second edit (caches warm for everything that is keyed on unchanged inputs)
    ni = [w for w in at.number_input if "annual_kwh" in (w.key or "")]
    ni[0].set_value(float(ni[0].value) + 100.0)
    _profile(f"{variant}_04_edit_annual_kwh_again", lambda: at.run())
    assert not at.exception
    # toggle a heating-related input if present (persons)
    pers = [w for w in at.number_input if "house_persons" in (w.key or "")]
    if pers:
        pers[0].set_value(int(pers[0].value) + 1)
        _profile(f"{variant}_05_edit_persons", lambda: at.run())
        assert not at.exception
    [tabs] = at.segmented_control
    for tab in ("Heizsysteme", "Wechselrichter", "PV-Felder", "Batterien"):
        tabs.set_value(tab)
        _profile(f"{variant}_06_tab_{tab}", lambda: at.run())
        assert not at.exception, at.exception
        [tabs] = at.segmented_control
    # widget census
    with open(OUT / "timings.txt", "a", encoding="utf-8") as fh:
        fh.write(f"{variant}: widgets number_input={len(at.number_input)} selectbox={len(at.selectbox)} "
                 f"checkbox={len(at.checkbox)} text_input={len(at.text_input)} markdown={len(at.markdown)}\n")
