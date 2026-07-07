"""Tests für swimspa_filter Config-Patch und Live-Abnahme-Hilfen."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import patch_swimspa_filter_config as patch_mod


def test_patch_inserts_swimspa_filter_after_swimspa(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "flexible_consumers": [
                    {"id": "swimspa", "name": "SwimSpa"},
                    {"id": "eauto", "name": "E-Auto"},
                ]
            }
        ),
        encoding="utf-8",
    )
    data = patch_mod._load_config(config_path)
    assert patch_mod.patch_config(data) is True
    ids = [c["id"] for c in data["flexible_consumers"]]
    assert ids == ["swimspa", "swimspa_filter", "eauto"]
    filter_item = data["flexible_consumers"][1]
    assert filter_item["daily_target_source"] == "loxone_remaining_hours"
    assert filter_item["filter_schedule"]["enabled"] is True


def test_patch_is_idempotent(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"flexible_consumers": [patch_mod.SWIMSPA_FILTER_BLOCK]}),
        encoding="utf-8",
    )
    data = patch_mod._load_config(config_path)
    assert patch_mod.patch_config(data) is False
