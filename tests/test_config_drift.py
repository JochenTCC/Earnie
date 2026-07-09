# tests/test_config_drift.py
from __future__ import annotations

from runtime_store.config_drift import find_config_drift, should_show_config_drift


def test_find_config_drift_reports_missing_top_level_and_nested_keys():
    example = {
        "awattar": {"url": "https://api.awattar.at/v1/marketdata", "fix_aufschlag_cent": 1.5},
        "file_paths_battery_simulation": {"path_cons_data": "runtime/cons_data_hourly.csv"},
        "flexible_consumers": [
            {
                "id": "eauto",
                "charging_schedule": {"forecast_when_absent": True},
            }
        ],
    }
    actual = {
        "awattar": {"url": "https://api.awattar.at/v1/marketdata"},
        "flexible_consumers": [{"id": "eauto", "name": "E-Auto"}],
    }

    items = find_config_drift(example, actual)
    paths = {item.path for item in items}

    assert "awattar.fix_aufschlag_cent" in paths
    assert "file_paths_battery_simulation" in paths
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
