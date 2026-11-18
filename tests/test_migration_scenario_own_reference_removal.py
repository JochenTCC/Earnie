"""dm6.scenario_own_reference_removal: own_reference goes, Live is always active in the SE."""
from __future__ import annotations

import pytest

from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY
from runtime_store.migration.steps.scenario_own_reference_removal import STEP


def _docs(scenarios: list[dict], live_id: str | None = "live") -> dict:
    config = {DATA_MODEL_KEY: CURRENT_DATA_MODEL}
    if live_id is not None:
        config["live_scenario_id"] = live_id
    return {
        "config.json": config,
        "backtesting_scenarios.json": {DATA_MODEL_KEY: CURRENT_DATA_MODEL, "scenarios": scenarios},
    }


def test_drops_own_reference_from_every_scenario():
    docs = _docs(
        [
            {"id": "live", "own_reference": True, "settings": {}},
            {"id": "b", "own_reference": False, "enabled": False, "settings": {}},
            {"id": "c", "settings": {}},
        ]
    )
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    assert result.changed_files == ("backtesting_scenarios.json",)
    scenarios = result.docs["backtesting_scenarios.json"]["scenarios"]
    assert scenarios == [
        {"id": "live", "settings": {}},
        {"id": "b", "enabled": False, "settings": {}},
        {"id": "c", "settings": {}},
    ]
    assert "own_reference" in docs["backtesting_scenarios.json"]["scenarios"][0]  # input untouched
    assert not STEP.detect(result.docs)


def test_switches_a_disabled_live_scenario_on():
    docs = _docs([{"id": "live", "enabled": False, "settings": {}}])
    assert STEP.detect(docs)
    scenarios = STEP.apply(docs, {}).docs["backtesting_scenarios.json"]["scenarios"]
    assert scenarios == [{"id": "live", "enabled": True, "settings": {}}]


def test_clean_pack_is_no_op():
    docs = _docs([{"id": "live", "settings": {}}, {"id": "b", "enabled": False, "settings": {}}])
    assert not STEP.detect(docs)
    assert STEP.apply(docs, {}).changed_files == ()


def test_without_live_id_only_the_key_goes():
    docs = _docs([{"id": "live", "enabled": False, "settings": {}}], live_id=None)
    assert not STEP.detect(docs)


def test_loader_rejects_a_leftover_key():
    from settings.scenarios import normalize_scenario

    with pytest.raises(ValueError, match="Konfig-Migration"):
        normalize_scenario({"id": "a", "own_reference": True, "settings": {}}, 0)


def test_loader_rejects_a_disabled_live_scenario():
    from settings.live_scenario import ensure_live_scenario_enabled

    with pytest.raises(ValueError, match="Live-Szenario 'live'"):
        ensure_live_scenario_enabled([{"id": "live", "enabled": False}], "live")
    ensure_live_scenario_enabled([{"id": "live", "enabled": True}, {"id": "b", "enabled": False}], "live")
