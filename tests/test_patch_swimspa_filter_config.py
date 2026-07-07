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
        json.dumps(
            {
                "flexible_consumers": [
                    {
                        "id": "swimspa",
                        "name": "SwimSpa",
                        "loxone_inputs": {
                            "power_name": "Ernie_Swim-Spa-P_act",
                            "subtract_consumer_ids": ["swimspa_filter"],
                        },
                    },
                    patch_mod.SWIMSPA_FILTER_BLOCK,
                ]
            }
        ),
        encoding="utf-8",
    )
    data = patch_mod._load_config(config_path)
    assert patch_mod.patch_config(data) is False


def test_patch_adds_shared_meter_subtraction_to_swimspa(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "flexible_consumers": [
                    {
                        "id": "swimspa",
                        "name": "SwimSpa",
                        "loxone_inputs": {"power_name": "Ernie_Swim-Spa-P_act"},
                    },
                    patch_mod.SWIMSPA_FILTER_BLOCK,
                ]
            }
        ),
        encoding="utf-8",
    )
    data = patch_mod._load_config(config_path)
    assert patch_mod.patch_config(data) is True
    swimspa = data["flexible_consumers"][0]
    assert swimspa["loxone_inputs"]["subtract_consumer_ids"] == ["swimspa_filter"]


def test_shared_meter_patch_idempotent(tmp_path: Path):
    consumers = [
        {
            "id": "swimspa",
            "loxone_inputs": {
                "power_name": "Ernie_Swim-Spa-P_act",
                "subtract_consumer_ids": ["swimspa_filter"],
            },
        }
    ]
    assert patch_mod.patch_swimspa_shared_meter(consumers) is False
    assert consumers[0]["loxone_inputs"]["subtract_consumer_ids"] == ["swimspa_filter"]
