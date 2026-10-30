# tests/test_config_drift.py
from __future__ import annotations

from runtime_store.config_drift import find_config_drift, should_show_config_drift


def test_find_config_drift_reports_missing_top_level_and_nested_keys():
    example = {
        "market_prices": {"missing_price_strategy": "forecast"},
        "scenario_explorer_conf": {"path_cons_data": "runtime/cons_data.csv"},
        "system": {"global_timeout": 10, "loop_timeout": 900},
    }
    actual = {"system": {"global_timeout": 10}}

    paths = {item.path for item in find_config_drift(example, actual)}

    assert paths == {"market_prices", "scenario_explorer_conf", "system.loop_timeout"}


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
        "system": {"global_timeout": 10, "ehal_loxone_http_port": 8541},
        "live_scenario_id": "live",
    }
    actual = {
        "market_prices": {"missing_price_strategy": "forecast"},
        "system": {
            "global_timeout": 10,
            "ehal_loxone_http_port": 8541,
        },
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
        "system": {"global_timeout": 10, "loxone_silent_mode": True},
        "live_scenario_id": "live",
    }
    actual = {
        "system": {"global_timeout": 10},
        "live_scenario_id": "live",
    }

    items = find_config_drift(example, actual)
    assert items == []


def test_load_config_drift_items_ignores_stale_pack_example(tmp_path, monkeypatch):
    """A stale config.example.json next to config.json must not drive the drift check."""
    import json

    from runtime_store import config_drift
    from runtime_store.persist_paths import bundled_config_example_file
    from settings.json_io import read_json_dict

    bundled = read_json_dict(bundled_config_example_file())
    assert "flexible_consumers" not in bundled
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps(bundled), encoding="utf-8")
    (config_dir / "config.example.json").write_text(
        json.dumps({**bundled, "flexible_consumers": []}), encoding="utf-8"
    )
    monkeypatch.delenv("EARNIE_CONFIG_PATH", raising=False)
    monkeypatch.setenv("EARNIE_ENV_PATH", str(tmp_path))

    assert config_drift.resolve_config_json_path() == str(config_dir / "config.json")
    assert config_drift.load_config_drift_items() == []


def test_repo_example_matches_earnie_env_config_shape():
    """Regression: live earnie_env config must not drift against config.example.json."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    example_path = repo_root / "share" / "config" / "config.example.json"
    live_path = repo_root / "earnie_env" / "config" / "config.json"
    if not live_path.is_file():
        import pytest

        pytest.skip("earnie_env/config/config.json nicht vorhanden")

    from settings.json_io import read_json_dict

    example = read_json_dict(str(example_path))
    actual = read_json_dict(str(live_path))
    assert find_config_drift(example, actual) == []
