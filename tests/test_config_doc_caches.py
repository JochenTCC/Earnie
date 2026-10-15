"""Process-wide mtime caches for house_profiles / components documents."""
from __future__ import annotations

import json
import os

import house_config.components_store as components_store
import house_config.profiles_store as profiles_store


def _minimal_house_profiles() -> dict:
    return {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 4000.0,
                "land": "AT",
                "latitude": 47.0,
                "longitude": 15.0,
                "timezone_name": "Europe/Vienna",
                "consumers": [],
            }
        ]
    }


def _minimal_components() -> dict:
    return {"inverters": [], "batteries": [], "pv_systems": []}


def test_house_profiles_doc_cache_skips_reread(tmp_path, monkeypatch):
    profiles_store.clear_house_profiles_doc_cache()
    path = tmp_path / "house_profiles.json"
    path.write_text(json.dumps(_minimal_house_profiles()), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.shadow.mode.is_shadow_config_readonly",
        lambda: False,
    )

    first = profiles_store.load_house_profiles_document(str(path))
    assert "home" in first["profiles"]

    open_count = {"n": 0}
    original_open = open

    def _counting_open(*args, **kwargs):
        # Only count the house_profiles path (encoding retries may open multiple times).
        if args and str(args[0]) == str(path):
            open_count["n"] += 1
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", _counting_open)
    second = profiles_store.load_house_profiles_document(str(path))
    assert second is first
    assert open_count["n"] == 0


def test_house_profiles_doc_cache_invalidates_on_mtime(tmp_path, monkeypatch):
    profiles_store.clear_house_profiles_doc_cache()
    path = tmp_path / "house_profiles.json"
    path.write_text(json.dumps(_minimal_house_profiles()), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.shadow.mode.is_shadow_config_readonly",
        lambda: False,
    )

    first = profiles_store.load_house_profiles_document(str(path))
    updated = _minimal_house_profiles()
    updated["profiles"][0]["label"] = "Renamed"
    path.write_text(json.dumps(updated), encoding="utf-8")
    # Ensure mtime advances even on coarse FS clocks.
    new_mtime = path.stat().st_mtime + 2.0
    os.utime(path, (new_mtime, new_mtime))

    second = profiles_store.load_house_profiles_document(str(path))
    assert second is not first
    assert second["profiles"]["home"]["label"] == "Renamed"


def test_house_profiles_save_clears_cache(tmp_path, monkeypatch):
    profiles_store.clear_house_profiles_doc_cache()
    path = tmp_path / "house_profiles.json"
    path.write_text(json.dumps(_minimal_house_profiles()), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.shadow.mode.is_shadow_config_readonly",
        lambda: False,
    )
    _ = profiles_store.load_house_profiles_document(str(path))
    # save expects wire shape (profiles as array), not the normalized id→profile map.
    to_save = _minimal_house_profiles()
    to_save["profiles"][0]["label"] = "ViaSave"
    profiles_store.save_house_profiles_document(str(path), to_save)
    reloaded = profiles_store.load_house_profiles_document(str(path))
    assert reloaded["profiles"]["home"]["label"] == "ViaSave"


def test_components_doc_cache_skips_reread(tmp_path, monkeypatch):
    components_store.clear_components_doc_cache()
    path = tmp_path / "components.json"
    path.write_text(json.dumps(_minimal_components()), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.shadow.mode.is_shadow_config_readonly",
        lambda: False,
    )

    first = components_store.load_components_document(str(path))
    open_count = {"n": 0}
    original_open = open

    def _counting_open(*args, **kwargs):
        if args and str(args[0]) == str(path):
            open_count["n"] += 1
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", _counting_open)
    second = components_store.load_components_document(str(path))
    assert second is first
    assert open_count["n"] == 0


def test_components_save_clears_cache(tmp_path, monkeypatch):
    components_store.clear_components_doc_cache()
    path = tmp_path / "components.json"
    path.write_text(json.dumps(_minimal_components()), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.shadow.mode.is_shadow_config_readonly",
        lambda: False,
    )
    _ = components_store.load_components_document(str(path))
    components_store.save_components_document(
        str(path),
        {
            "inverters": [
                {
                    "id": "wr_main",
                    "label": "WR",
                    "type": "hybrid",
                    "ac_connection": "grid_tied",
                    "control": "full",
                    "efficiency": 0.97,
                }
            ],
            "batteries": [
                {
                    "id": "bat1",
                    "label": "Bat",
                    "inverter_id": "wr_main",
                    "battery_capacity_kwh": 10.0,
                    "battery_max_charge_power_kw": 5.0,
                    "battery_max_discharge_power_kw": 5.0,
                    "battery_efficiency": 0.95,
                    "battery_min_soc": 10.0,
                    "battery_max_soc": 90.0,
                    "threshold_power": 0.05,
                    "regulates_on": "grid",
                    "battery_wear": {"enabled": False},
                }
            ],
            "pv_systems": [],
        },
    )
    reloaded = components_store.load_components_document(str(path))
    assert len(reloaded["batteries"]) == 1
    assert reloaded["batteries"][0]["id"] == "bat1"
