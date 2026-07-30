"""append_monthly_rate + config.reload picks up new month rows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Config
from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID
from house_config.tariffs_store import append_monthly_rate, load_tariffs_document


def _minimal_monthly_export_doc() -> dict:
    return {
        "import_tariffs": [
            {
                "id": "fixed_imp",
                "label": "Fix",
                "type": "fixed_cent",
                "supplier_id": "fix_supplier",
                "land": "AT",
                "fix_cent_kwh": 30.0,
                "prices_include_vat": True,
                "vat_percent": 0.0,
            }
        ],
        "export_tariffs": [
            {
                "id": "monthly_exp",
                "label": "Monatlich",
                "type": "monthly_table",
                "supplier_id": "exp_supplier",
                "land": "AT",
                "prices_include_vat": True,
                "vat_percent": 0.0,
                "monthly_rates": [
                    {"year": 2026, "month": 6, "tariff_cent_kwh": 5.5},
                ],
            }
        ],
    }


def _write_live_pack(config_dir: Path, tariffs: dict) -> None:
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "live_scenario_id": DEFAULT_LIVE_SCENARIO_ID,
                "system": {"global_timeout": 10, "loop_timeout": 900},
                "loxone_blocks": {
                    "soc_name": "Battery_SOC",
                    "pv_power_name": "PV_Act",
                    "battery_power_name": "Battery_Act",
                    "grid_power_name": "Grid_Act",
                    "target_charge_power_name": "Target_Charge",
                    "target_discharge_power_name": "Target_Discharge",
                    "control_cmd_name": "Control_Cmd",
                },
                "planning_horizon": {"mode": "sunrise_window"},
                "scenario_explorer_conf": {
                    "path_cons_data": "runtime/cons_data_hourly.csv"
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        json.dumps(
            {
                "batteries": [
                    {
                        "id": "home_5kwh",
                        "label": "5 kWh",
                        "battery_capacity_kwh": 5.0,
                        "battery_max_power_kw": 2.5,
                        "battery_efficiency": 0.97,
                        "battery_min_soc": 10.0,
                        "battery_max_soc": 100.0,
                        "threshold_power": 0.05,
                    }
                ],
                "pv_systems": [
                    {
                        "id": "roof",
                        "label": "Roof",
                        "kwp": 10.0,
                        "pv_tilt": 30.0,
                        "pv_azimuth": 180.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "efh",
                        "label": "EFH",
                        "land": "AT",
                        "annual_kwh": 4000,
                        "latitude": 48.2,
                        "longitude": 16.3,
                        "consumers": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": DEFAULT_LIVE_SCENARIO_ID,
                        "label": "Live",
                        "settings": {
                            "battery_id": "home_5kwh",
                            "pv_system_id": "roof",
                            "import_tariff_id": "fixed_imp",
                            "export_tariff_id": "monthly_exp",
                            "house_profile_id": "efh",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "tariffs.json").write_text(
        json.dumps(tariffs),
        encoding="utf-8",
    )


def test_append_monthly_rate_adds_and_replaces(tmp_path):
    path = tmp_path / "tariffs.json"
    path.write_text(json.dumps(_minimal_monthly_export_doc()), encoding="utf-8")

    append_monthly_rate(
        str(path),
        side="export",
        tariff_id="monthly_exp",
        year=2026,
        month=7,
        tariff_cent_kwh=6.2,
    )
    doc = load_tariffs_document(str(path))
    rates = {
        (y, m): c
        for y, m, c in doc["export_tariffs"]["monthly_exp"]["monthly_rates"]
    }
    assert rates[(2026, 7)] == pytest.approx(6.2)

    append_monthly_rate(
        str(path),
        side="export",
        tariff_id="monthly_exp",
        year=2026,
        month=7,
        tariff_cent_kwh=6.8,
    )
    doc = load_tariffs_document(str(path))
    rates = {
        (y, m): c
        for y, m, c in doc["export_tariffs"]["monthly_exp"]["monthly_rates"]
    }
    assert rates[(2026, 7)] == pytest.approx(6.8)
    assert len(rates) == 2


def test_append_monthly_rate_rejects_non_monthly(tmp_path):
    path = tmp_path / "tariffs.json"
    path.write_text(json.dumps(_minimal_monthly_export_doc()), encoding="utf-8")
    with pytest.raises(ValueError, match="nur monthly_table"):
        append_monthly_rate(
            str(path),
            side="import",
            tariff_id="fixed_imp",
            year=2026,
            month=7,
            tariff_cent_kwh=10.0,
        )


def test_reload_config_picks_up_appended_monthly_rate(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_live_pack(config_dir, _minimal_monthly_export_doc())
    tariffs_path = str(config_dir / "tariffs.json")

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=tariffs_path,
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )
    before = {
        (y, m): c for y, m, c in cfg.get_resolved_runtime_settings()["_monthly_fixed_tariffs"]
    }
    assert (2026, 7) not in before

    append_monthly_rate(
        tariffs_path,
        side="export",
        tariff_id="monthly_exp",
        year=2026,
        month=7,
        tariff_cent_kwh=6.4,
    )
    cfg.reload()
    after = {
        (y, m): c for y, m, c in cfg.get_resolved_runtime_settings()["_monthly_fixed_tariffs"]
    }
    assert after[(2026, 7)] == pytest.approx(6.4)
