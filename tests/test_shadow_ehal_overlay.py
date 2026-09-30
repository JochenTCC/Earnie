"""Shadow EHAL bindings overlay (runtime merge, config stays read-only)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from house_config.profiles_store import (
    load_house_profiles_document,
    save_house_profiles_document,
)
from runtime_store.shadow.ehal_overlay import (
    apply_overlay_to_house,
    clear_overlay,
    overlay_path,
    upsert_entity_bindings,
)
from runtime_store.shadow.errors import ConfigReadOnlyError
from settings.json_io import write_json_dict


@pytest.fixture(autouse=True)
def _shadow_runtime(tmp_path, monkeypatch):
    runtime = tmp_path / "rt"
    runtime.mkdir()
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(runtime))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    clear_overlay()
    yield
    clear_overlay()


def _base_house() -> dict:
    return {
        "plant": {"ehal_bindings": {"sens_grid_power_active": "Prod_Grid"}},
        "profiles": {
            "live": {
                "id": "live",
                "label": "Live",
                "annual_kwh": 1000.0,
                "consumers": [
                    {
                        "id": "heatpump",
                        "label": "WP",
                        "type": "generic",
                        "nominal_power_kw": 3.0,
                        "ehal_bindings": {"sens_temperature_buffer": "Prod_T"},
                    }
                ],
            }
        },
    }


def test_upsert_and_apply_consumer_overlay():
    upsert_entity_bindings(
        profile_id="live",
        entity_id="heatpump",
        bindings={"sens_temperature_buffer": "Shadow_T", "sens_hp_power": "Shadow_P"},
    )
    merged = apply_overlay_to_house(_base_house())
    plant = merged["plant"]["ehal_bindings"]
    assert plant["sens_grid_power_active"] == "Prod_Grid"
    hp = merged["profiles"]["live"]["consumers"][0]["ehal_bindings"]
    assert hp["sens_temperature_buffer"] == "Shadow_T"
    assert hp["sens_hp_power"] == "Shadow_P"


def test_upsert_plant_overlay():
    upsert_entity_bindings(
        profile_id="live",
        entity_id="plant",
        bindings={"sens_grid_power_active": "Shadow_Grid"},
    )
    merged = apply_overlay_to_house(_base_house())
    assert merged["plant"]["ehal_bindings"] == {
        "sens_grid_power_active": "Shadow_Grid"
    }


def test_load_house_profiles_merges_overlay(tmp_path, monkeypatch):
    from house_config.profiles_store import save_house_profiles_document as _save

    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    path = tmp_path / "config" / "house_profiles.json"
    doc = {
        "profiles": [
            {
                "id": "live",
                "label": "Live",
                "annual_kwh": 1000.0,
                "consumers": [
                    {
                        "id": "heatpump",
                        "label": "WP",
                        "type": "generic",
                        "nominal_power_kw": 3.0,
                        "ehal_bindings": {"sens_temperature_buffer": "Prod_T"},
                    }
                ],
            }
        ],
        "plant": {"ehal_bindings": {"sens_grid_power_active": "Prod_Grid"}},
    }
    _save(str(path), doc)
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    upsert_entity_bindings(
        profile_id="live",
        entity_id="heatpump",
        bindings={"sens_temperature_buffer": "Shadow_T"},
    )
    loaded = load_house_profiles_document(str(path))
    hp = loaded["profiles"]["live"]["consumers"][0]["ehal_bindings"]
    assert hp["sens_temperature_buffer"] == "Shadow_T"


def test_save_house_profiles_raises_in_shadow(tmp_path):
    target = tmp_path / "config" / "house_profiles.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigReadOnlyError):
        save_house_profiles_document(str(target), _base_house())


def test_config_json_still_readonly(tmp_path):
    target = tmp_path / "config" / "config.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigReadOnlyError):
        write_json_dict(str(target), {"earnie_data_model": 3})


def test_overlay_path_under_runtime(tmp_path):
    path = Path(overlay_path())
    assert path.name == "shadow_ehal_bindings.json"
    assert path.parent == tmp_path / "rt"
    upsert_entity_bindings(
        profile_id="live", entity_id="plant", bindings={"a": "b"}
    )
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["plant_bindings"]["a"] == "b"
