"""Hauskonfigurator saves: profile order kept (review 2a-5), Shadow lock on the
scenario file (2a-3)."""
from __future__ import annotations

import json

import pytest

from runtime_store.shadow.errors import ConfigReadOnlyError
from tests.test_entity_id_lock import profiles_env  # noqa: F401 — fixture


def _profile(profile_id: str, label: str) -> dict:
    return {
        "id": profile_id,
        "label": label,
        "annual_kwh": 5000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "netznutzung": {"area_id": "user_no_grid_fee"},
        "consumers": [],
    }


def test_saving_a_profile_keeps_its_position(profiles_env):
    from ui.house_config_io import house_profile_write_pending, upsert_house_profile

    for pid, label in (("a", "A"), ("b", "B"), ("c", "C")):
        upsert_house_profile(_profile(pid, label))

    def _order() -> list[str]:
        raw = json.loads(profiles_env["profiles"].read_text(encoding="utf-8"))
        return [p["id"] for p in raw["profiles"]]

    assert _order() == ["a", "b", "c"]
    # Opening an unchanged profile that is not the last one writes nothing.
    assert house_profile_write_pending(_profile("a", "A")) is False
    upsert_house_profile(_profile("a", "A neu"))
    assert _order() == ["a", "b", "c"]


def test_scenario_file_write_refused_in_shadow(tmp_path, monkeypatch):
    from ui.house_config_io import write_json_document

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    target = cfg_dir / "backtesting_scenarios.json"
    target.write_text('{"scenarios": []}', encoding="utf-8")
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg_dir))
    monkeypatch.delenv("EARNIE_SHADOW_FEED_PATH", raising=False)
    with pytest.raises(ConfigReadOnlyError):
        write_json_document(str(target), {"scenarios": [{"id": "x"}]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"scenarios": []}
