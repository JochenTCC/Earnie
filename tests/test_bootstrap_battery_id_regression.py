"""Regression: legacy settings.battery_id — soft coerce without silent bootstrap migrate."""
from __future__ import annotations

import json

from house_config.scenario_resolution import resolve_scenario_settings
from runtime_store import bootstrap
from runtime_store.data_model import CURRENT_DATA_MODEL


def test_bootstrap_does_not_silently_migrate_battery_id(tmp_path, monkeypatch):
    """ConfigMigration P2: live pack content migrates via wizard/CLI, not bootstrap."""
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(tmp_path / "config" / "config.json"))
    monkeypatch.delenv("EARNIE_BACKTESTING_SCENARIOS_PATH", raising=False)
    monkeypatch.delenv("EARNIE_COMPONENTS_PATH", raising=False)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    scenarios_path = config_dir / "backtesting_scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            {
                "earnie_data_model": CURRENT_DATA_MODEL,
                "scenarios": [
                    {
                        "id": "live",
                        "label": "Live",
                        "settings": {"battery_id": "10_kwh_speicher"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    components_path = config_dir / "components.json"
    components_path.write_text(
        json.dumps(
            {
                "earnie_data_model": CURRENT_DATA_MODEL,
                "batteries": [],
                "pv_systems": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        bootstrap,
        "resolve_backtesting_scenarios_json_path",
        lambda: str(scenarios_path),
    )
    monkeypatch.setattr(
        bootstrap,
        "resolve_components_json_path",
        lambda: str(components_path),
    )
    monkeypatch.setattr(
        "runtime_store.shadow.mode.is_shadow_mode",
        lambda: False,
    )

    before = scenarios_path.read_text(encoding="utf-8")
    bootstrap._bootstrap_runtime_data_artifacts(shadow=False)
    after = scenarios_path.read_text(encoding="utf-8")
    assert after == before
    scenarios = json.loads(after)
    assert "battery_id" in scenarios["scenarios"][0]["settings"]


def test_resolve_scenario_settings_coerces_legacy_battery_id(monkeypatch):
    """Regression: live resolve must not abort on singular battery_id before disk migrate."""
    bat = {
        "id": "10_kwh_speicher",
        "label": "10 kWh",
        "inverter_id": "wr_main",
        "battery_capacity_kwh": 10.0,
        "battery_max_charge_power_kw": 5.0,
        "battery_max_discharge_power_kw": 5.0,
        "battery_max_power_kw": 5.0,
        "battery_efficiency": 0.97,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "threshold_power": 0.02,
        "regulates_on": "grid",
        "standby_power_kw": 0.05,
        "control": "full",
        "limits_from_live": False,
        "ehal_bindings": {},
        "battery_wear": None,
    }
    wr = {
        "id": "wr_main",
        "label": "Haupt-WR",
        "type": "hybrid",
        "ac_connection": "grid_tied",
        "control": "full",
        "efficiency": 0.97,
        "ehal_bindings": {},
    }
    monkeypatch.setattr(
        "house_config.scenario_resolution.load_tariffs_document",
        lambda _path: {"import_tariffs": [], "export_tariffs": []},
    )
    monkeypatch.setattr(
        "house_config.scenario_resolution.resolve_import_tariff_into_settings",
        lambda settings, _doc: settings,
    )
    monkeypatch.setattr(
        "house_config.scenario_resolution.resolve_export_tariff_into_settings",
        lambda settings, _doc, monthly_rates_holder=None: settings,
    )
    resolved = resolve_scenario_settings(
        {"battery_id": "10_kwh_speicher"},
        raw_config={"live_scenario_id": "live"},
        components={"inverters": [wr], "batteries": [bat], "pv_systems": []},
        tariffs_path="unused",
        house_profiles_path="unused",
    )
    assert "battery_id" not in resolved
    assert resolved["battery_capacity_kwh"] == 10.0
    assert len(resolved["_planning_batteries"]) == 1
