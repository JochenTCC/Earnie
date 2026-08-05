"""Fail-fast data-model checks (no soft v1/v2 upgrades)."""
from __future__ import annotations

import pytest

from runtime_store.data_model import (
    CURRENT_DATA_MODEL,
    DataModelError,
    ensure_compatible,
    reject_legacy_config_structure,
)


def test_ensure_compatible_rejects_v1_and_v2():
    with pytest.raises(DataModelError, match="nicht kompatibel"):
        ensure_compatible({"earnie_data_model": 1}, label="x.json")
    with pytest.raises(DataModelError, match="nicht kompatibel"):
        ensure_compatible(
            {
                "earnie_data_model": 2,
                "live_scenario_id": "live",
                "scenario_explorer_conf": {"path_cons_data": "runtime/x.csv"},
            },
            label="config.json",
        )


def test_ensure_compatible_rejects_missing_tag():
    with pytest.raises(DataModelError, match="fehlt"):
        ensure_compatible({"live_scenario_id": "live"}, label="config.json")


def test_ensure_compatible_accepts_v3_clean_config():
    doc = {
        "earnie_data_model": CURRENT_DATA_MODEL,
        "live_scenario_id": "live",
        "scenario_explorer_conf": {"path_cons_data": "runtime/x.csv"},
    }
    assert ensure_compatible(doc, label="config.json") == CURRENT_DATA_MODEL


def test_reject_legacy_config_structure_legacy_block():
    with pytest.raises(DataModelError, match="scenario_explorer_conf"):
        reject_legacy_config_structure(
            {
                "earnie_data_model": 3,
                "live_scenario_id": "live",
                "file_paths_battery_simulation": {"path_cons_data": "x.csv"},
            },
            label="config.json",
        )


def test_reject_legacy_config_structure_removed_path_keys():
    with pytest.raises(DataModelError, match="path_consumption"):
        ensure_compatible(
            {
                "earnie_data_model": CURRENT_DATA_MODEL,
                "live_scenario_id": "live",
                "scenario_explorer_conf": {
                    "path_cons_data": "runtime/x.csv",
                    "path_consumption": "a.csv",
                    "path_production": "b.csv",
                },
            },
            label="config.json",
        )
