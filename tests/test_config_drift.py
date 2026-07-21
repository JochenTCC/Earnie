# tests/test_config_drift.py
from __future__ import annotations

from runtime_store.config_drift import find_config_drift, should_show_config_drift


def test_find_config_drift_reports_missing_top_level_and_nested_keys():
    example = {
        "market_prices": {"missing_price_strategy": "forecast"},
        "scenario_explorer_conf": {"path_cons_data": "runtime/cons_data_hourly.csv"},
        "flexible_consumers": [
            {
                "id": "eauto",
                "charging_schedule": {"forecast_when_absent": True},
            }
        ],
    }
    actual = {
        "flexible_consumers": [{"id": "eauto", "name": "E-Auto"}],
    }

    items = find_config_drift(example, actual)
    paths = {item.path for item in items}

    assert "market_prices" in paths
    assert "scenario_explorer_conf" in paths
    assert "flexible_consumers[id=eauto].charging_schedule" in paths


def test_find_config_drift_ignores_missing_consumers_when_actual_list_empty():
    example = {
        "flexible_consumers": [{"id": "swimspa", "name": "SwimSpa", "nominal_power_kw": 2.8}],
    }
    actual = {"flexible_consumers": []}

    items = find_config_drift(example, actual)
    assert items == []


def test_should_show_config_drift_false_during_planning_onboarding(monkeypatch):
    monkeypatch.setattr(
        "ui.setup_readiness.needs_planning_onboarding",
        lambda: True,
    )
    assert should_show_config_drift() is False


def test_should_show_config_drift_true_after_live_config(monkeypatch):
    monkeypatch.setattr(
        "ui.setup_readiness.needs_planning_onboarding",
        lambda: False,
    )
    assert should_show_config_drift() is True


def test_find_config_drift_no_legacy_blocks_for_2_0_migrated_config():
    """2.0 configs omit root eauto_milp, appliances[], system.loxone_silent_mode."""
    example = {
        "market_prices": {"missing_price_strategy": "forecast"},
        "system": {"global_timeout": 10, "event_triggers": []},
        "flexible_consumers": [],
        "live_scenario_id": "live",
    }
    actual = {
        "market_prices": {"missing_price_strategy": "forecast"},
        "system": {
            "global_timeout": 10,
            "event_trigger_enabled": True,
            "event_triggers": [],
        },
        "flexible_consumers": [],
        "live_scenario_id": "live",
    }

    items = find_config_drift(example, actual)
    assert items == []


def test_find_config_drift_ignores_legacy_blocks_when_example_stale_2_0_actual():
    """Stale config.example.json (pre-2.0) must not drift against migrated live config."""
    example = {
        "eauto_milp": {"live_modus_a_min_remaining_kwh": 2.8},
        "batteries": [{"id": "default_5kwh"}],
        "pv_systems": [{"id": "roof_south"}],
        "appliances": [{"id": "waschmaschine"}],
        "system": {"global_timeout": 10, "loxone_silent_mode": True, "event_triggers": []},
        "flexible_consumers": [],
        "live_scenario_id": "live",
    }
    actual = {
        "system": {"global_timeout": 10, "event_triggers": []},
        "flexible_consumers": [],
        "live_scenario_id": "live",
    }

    items = find_config_drift(example, actual)
    assert items == []


def test_repo_example_matches_earnie_env_config_shape():
    """Regression: live earnie_env config must not drift against config.example.json."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    example_path = repo_root / "share" / "config" / "config.example.json"
    live_path = repo_root / "earnie_env" / "config" / "config.json"
    if not live_path.is_file():
        import pytest

        pytest.skip("earnie_env/config/config.json nicht vorhanden")

    import json

    example = json.loads(example_path.read_text(encoding="utf-8"))
    actual = json.loads(live_path.read_text(encoding="utf-8"))
    assert find_config_drift(example, actual) == []
