"""The shipped ``share/config/*.example.json`` files must form a loadable, current pack."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from house_config.baseload import ensure_baseload_not_over_allocated
from house_config.profiles_store import load_house_profiles_document, profile_list
from runtime_store.migration import plan_migration
from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

SHARE_CONFIG = Path(__file__).resolve().parents[1] / "share" / "config"
EXAMPLES = sorted(SHARE_CONFIG.glob("*.example.json"))


@pytest.fixture()
def example_pack(tmp_path: Path) -> Path:
    for example in EXAMPLES:
        shutil.copy2(example, tmp_path / example.name.replace(".example", ""))
    shutil.copy2(SHARE_CONFIG / "grid_fees.json", tmp_path / "grid_fees.json")
    return tmp_path


def test_examples_are_present():
    assert {path.name for path in EXAMPLES} >= {
        "config.example.json",
        "house_profiles.example.json",
        "components.example.json",
        "tariffs.example.json",
        "backtesting_scenarios.example.json",
    }


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.name)
def test_example_is_valid_json(example: Path):
    assert isinstance(json.loads(example.read_text(encoding="utf-8")), dict)


def test_example_pack_needs_no_migration(example_pack: Path):
    plan = plan_migration(example_pack)
    assert not plan.blockers, [b.message_de for b in plan.blockers]
    assert plan.pending_step_ids == ()


def test_example_house_profiles_load_and_fit_annual_kwh(example_pack: Path, monkeypatch):
    install_open_meteo_climate_mock(monkeypatch)
    doc = load_house_profiles_document(str(example_pack / "house_profiles.json"))
    profiles = profile_list(doc)
    assert profiles
    for profile in profiles:
        ensure_baseload_not_over_allocated(profile, context=str(profile.get("id")))
