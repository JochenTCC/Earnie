"""Fail-fast gates for removed config.json blocks (2.0 / 1.26.0 P6)."""
from __future__ import annotations

from settings import appliances as appliance_settings


def reject_legacy_config_blocks(raw_config: dict) -> None:
    if raw_config.get("file_paths_battery_simulation") is not None:
        raise ValueError(
            "Block 'file_paths_battery_simulation' in config.json wurde umbenannt zu "
            "'scenario_explorer_conf'."
        )
    sim = raw_config.get("scenario_explorer_conf")
    if isinstance(sim, dict):
        leftover = [
            key
            for key in ("path_consumption", "path_production")
            if key in sim
        ]
        if leftover:
            raise ValueError(
                "In scenario_explorer_conf sind entfernt: "
                + ", ".join(repr(k) for k in leftover)
                + ". Zeitraumgrenzen kommen aus cons_data / Hausprofil-CSVs "
                "(data-model v3)."
            )
    if raw_config.get("awattar") is not None:
        raise ValueError(
            "Block 'awattar' in config.json ist entfernt (1.26.0 P6). "
            "Aufschläge gehören in tariffs.json; die API-URL wird aus "
            "import_tariff_id (land) abgeleitet."
        )
    if raw_config.get("battery_wear") is not None:
        raise ValueError(
            "Globaler Block 'battery_wear' ist entfernt (1.26.0 P6). "
            "Verschleiß pro batteries[]-Eintrag konfigurieren."
        )
    if raw_config.get("batteries") is not None:
        raise ValueError(
            "Block 'batteries' in config.json ist entfernt (2.0 Components). "
            "Batteriespezifikationen gehören in components.json."
        )
    if raw_config.get("pv_systems") is not None:
        raise ValueError(
            "Block 'pv_systems' in config.json ist entfernt (2.0 Components). "
            "PV-Anlagen gehören in components.json."
        )
    if raw_config.get("eauto_milp") is not None:
        raise ValueError(
            "Block 'eauto_milp' in config.json ist entfernt (2.0). "
            "MILP-Parameter gehören in charging_schedule.milp am E-Auto-Verbraucher "
            "(Hausprofil / bridged flexible_consumers)."
        )
    appliance_settings.reject_legacy_appliances_block(raw_config)


def reject_legacy_runtime_settings_block(raw_config: dict) -> None:
    if raw_config.get("runtime_settings") is not None:
        from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID

        raise ValueError(
            "Block 'runtime_settings' in config.json ist entfernt (2.0 P2). "
            "Live-Szenario als Eintrag in backtesting_scenarios.json "
            f"(live_scenario_id, Standard: '{DEFAULT_LIVE_SCENARIO_ID}')."
        )
