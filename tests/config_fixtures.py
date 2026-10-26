"""Gemeinsame Test-Config-Hilfen (2.0 P2: Live-Szenario statt runtime_settings)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID

_BACKTESTING_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "backtesting"
GRID_FEE_FILES = ("grid_fees.json", "user_grid_fees.json")


def copy_fixture_grid_fees(config_dir: Path) -> None:
    """Grid catalog + user areas (``user_test_home``, ``user_no_grid_fee``) next to config.json.

    Data model 5: every house profile resolves its ``netznutzung.area_id`` against these files.
    """
    for name in GRID_FEE_FILES:
        shutil.copy(_BACKTESTING_FIXTURE_DIR / name, config_dir / name)


def tariff_doc(doc: dict) -> dict:
    """A tariffs.json / user_tariffs.json payload on the current tariff format."""
    from runtime_store.data_model import CURRENT_TARIFF_FORMAT, TARIFF_FORMAT_KEY

    return {TARIFF_FORMAT_KEY: CURRENT_TARIFF_FORMAT, **doc}


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
            "pv_power_name": "pv_act",
            "battery_power_name": "bat",
            "grid_power_name": "grid",
            "target_charge_power_name": "t_charge",
            "target_discharge_power_name": "t_discharge",
            "control_cmd_name": "cmd",
        },
        "planning_horizon": {"mode": "sunrise_window"},
        "scenario_explorer_conf": {
            "path_cons_data": "runtime/cons_data.csv",
        },
    }
    if extra:
        payload.update(extra)
    return payload


def default_live_settings() -> dict:
    return {
        "battery_ids": [],
        "pv_system_ids": [],
        "house_profile_id": "",
        "import_tariff_id": "",
        "export_tariff_id": "",
    }


def main_hybrid_inverter(**overrides) -> dict:
    """Default hybrid inverter stub for test components.json payloads."""
    from house_config.inverter import DEFAULT_INVERTER_EFFICIENCY

    base = {
        "id": "wr_main",
        "label": "Haupt-WR",
        "type": "hybrid",
        "ac_connection": "grid_tied",
        "control": "full",
        "efficiency": DEFAULT_INVERTER_EFFICIENCY,
        "ehal_bindings": {},
    }
    base.update(overrides)
    return base


def house_battery_stub(**overrides) -> dict:
    """Minimal house battery for components.json (Topology P1: regulates_on)."""
    base = {
        "id": "home",
        "label": "Haus",
        "inverter_id": "wr_main",
        "battery_capacity_kwh": 5.0,
        "battery_max_charge_power_kw": 2.5,
        "battery_max_discharge_power_kw": 2.5,
        "battery_efficiency": 0.97,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "threshold_power": 0.05,
        "control": "full",
        "regulates_on": "grid",
        "ehal_bindings": {},
        "battery_wear": {"enabled": False},
    }
    base.update(overrides)
    return base


def minimal_components_payload(*, extra: dict | None = None) -> dict:
    payload = {"inverters": [], "batteries": [], "pv_systems": []}
    if extra:
        payload.update(extra)
    return payload


def write_minimal_config_tree(
    tmp_path: Path,
    *,
    config_payload: dict | None = None,
    components_payload: dict | None = None,
    live_settings: dict | None = None,
) -> tuple[str, str]:
    """Schreibt config.json, components.json und backtesting_scenarios.json."""
    from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    payload = config_payload or minimal_config_payload()
    config_path = config_dir / "config.json"
    # Tagged like real pack files: recorder replay migrates archived snapshots and rejects
    # untagged Earnie-track files (data model 5).
    config_path.write_text(
        json.dumps({DATA_MODEL_KEY: CURRENT_DATA_MODEL, **payload}), encoding="utf-8"
    )
    copy_fixture_grid_fees(config_dir)
    # Own deviation rules next to config.json: the default path would be the developer's site.
    shutil.copy(
        _BACKTESTING_FIXTURE_DIR.parents[2] / "share" / "config" / "deviation_rules.example.json",
        config_dir / "deviation_rules.json",
    )
    components_path = config_dir / "components.json"
    components_path.write_text(
        json.dumps(
            {
                DATA_MODEL_KEY: CURRENT_DATA_MODEL,
                **(components_payload or minimal_components_payload()),
            }
        ),
        encoding="utf-8",
    )
    scenarios_path = config_dir / "backtesting_scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            {
                DATA_MODEL_KEY: CURRENT_DATA_MODEL,
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
