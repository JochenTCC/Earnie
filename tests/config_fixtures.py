"""Gemeinsame Test-Config-Hilfen (2.0 P2: Live-Szenario statt runtime_settings)."""
from __future__ import annotations

import json
from pathlib import Path

from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID


def minimal_config_payload(
    *,
    live_settings: dict | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "live_scenario_id": DEFAULT_LIVE_SCENARIO_ID,
        "system": {
            "global_timeout": 10,
            "loop_timeout": 900,
        },
        "loxone_blocks": {
            "soc_name": "soc",
            "pv_counter_name": "pv",
            "log_filename": "log.csv",
            "pv_tuning_log_file": "pv.csv",
            "pv_power_name": "pv_act",
            "battery_power_name": "bat",
            "grid_power_name": "grid",
            "target_soc_name": "t_soc",
            "target_charge_power_name": "t_charge",
            "target_discharge_power_name": "t_discharge",
            "control_cmd_name": "cmd",
        },
        "batteries": [],
        "pv_systems": [],
        "planning_horizon": {"mode": "sunset_window"},
        "file_paths_battery_simulation": {
            "path_cons_data": "runtime/cons_data_hourly.csv",
        },
        "flexible_consumers": [],
    }
    if extra:
        payload.update(extra)
    return payload


def default_live_settings() -> dict:
    return {
        "battery_id": "",
        "pv_system_id": "",
        "house_profile_id": "",
        "import_tariff_id": "",
        "export_tariff_id": "",
    }


def write_minimal_config_tree(
    tmp_path: Path,
    *,
    config_payload: dict | None = None,
    live_settings: dict | None = None,
) -> tuple[str, str]:
    """Schreibt config.json und backtesting_scenarios.json; gibt Pfade zurück."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    payload = config_payload or minimal_config_payload()
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    scenarios_path = config_dir / "backtesting_scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": payload.get("live_scenario_id", DEFAULT_LIVE_SCENARIO_ID),
                        "label": "Live",
                        "settings": live_settings or default_live_settings(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(config_path), str(scenarios_path)
