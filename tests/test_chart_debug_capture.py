"""Tests für Chart-Debug-ZIP-Export."""
from __future__ import annotations

import json
import os
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import config
from runtime_store.chart_debug_capture import (
    build_capture_payload,
    resolve_output_dir,
    write_capture_zip,
)
from ui.chart_context import build_live_chart_context
from ui.simulation_results import OptimizationDisplayBundle, build_optimization_display_bundle

_TZ = ZoneInfo("Europe/Vienna")
_CONFIG_ENV_KEYS = (
    "ENERGY_OPTIMIZER_CONFIG_PATH",
    "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
    "ENERGY_OPTIMIZER_OFFLINE",
    "ENERGY_OPTIMIZER_RUNTIME_DIR",
)


@contextmanager
def _chart_debug_config(tmp_path, monkeypatch, *, enabled: bool):
    """Mini-Config für Tests; stellt danach Projekt-Config wieder her."""
    prev = {key: os.environ.get(key) for key in _CONFIG_ENV_KEYS}
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))
    from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree

    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(
            extra={
                "ui": {
                    "chart_debug_capture_enabled": enabled,
                    "chart_debug_capture_dir": "chart_debug",
                }
            }
        ),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", config_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH", scenarios_path)
    config.reinit_config()
    try:
        yield config_path
    finally:
        for key, value in prev.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        config.reinit_config()


def _sample_bundle(now: datetime) -> OptimizationDisplayBundle:
    chart_context = build_live_chart_context(0, 0, now=now)
    savings_info = {
        "optimized_cost_euro": 1.0,
        "matched_baseline_cost_euro": 1.2,
        "savings_matched_euro": 0.2,
        "optimized_rows": [],
        "baseline_rows": [],
    }
    optimized_df = pd.DataFrame(
        [{
            "slot_datetime": chart_context.chart_window.start,
            "Uhrzeit": chart_context.chart_window.start.strftime("%d.%m. %H:%M"),
            "Simulierter SoC (%)": 42.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Preis extrapoliert": False,
        }]
    )
    return build_optimization_display_bundle(
        savings_info,
        optimized_df,
        pd.DataFrame(),
        chart_context=chart_context,
        optimization_matrix=optimized_df.to_dict("records"),
    )


def test_chart_debug_capture_config_default_disabled(tmp_path, monkeypatch):
    with _chart_debug_config(tmp_path, monkeypatch, enabled=False):
        assert config.get_ui_chart_debug_capture_enabled() is False


def test_chart_debug_capture_config_enabled(tmp_path, monkeypatch):
    with _chart_debug_config(tmp_path, monkeypatch, enabled=True):
        assert config.get_ui_chart_debug_capture_enabled() is True
        assert resolve_output_dir().endswith("chart_debug")


def test_write_capture_zip_contains_manifest(tmp_path, monkeypatch):
    with _chart_debug_config(tmp_path, monkeypatch, enabled=True):
        rules_path = tmp_path / "deviation_rules.json"
        model_path = tmp_path / "runtime" / "price_model_coefficients.json"
        cons_data_path = tmp_path / "runtime" / "cons_data_hourly.csv"
        rules_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tolerances": {"power_kw": 0.2},
                    "categories": {
                        "hint": {
                            "label": "Hinweis",
                            "symbol": "triangle-up",
                            "color": "#f1c40f",
                        },
                        "warning": {
                            "label": "Warnung",
                            "symbol": "diamond",
                            "color": "#e67e22",
                        },
                        "error": {
                            "label": "Fehler",
                            "symbol": "octagon",
                            "color": "#c0392b",
                        },
                    },
                    "rules": [],
                    "fallback": {"on_unclassified_mismatch": "warning"},
                }
            ),
            encoding="utf-8",
        )
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_text('{"version": 2, "coefficients": {}}', encoding="utf-8")
        cons_data_path.write_text("timestamp;total_kw;baseload_kw;pv_kw;source\n", encoding="utf-8")
        config_path = Path(os.environ["ENERGY_OPTIMIZER_CONFIG_PATH"])
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        cfg["market_prices"] = {"forecast_model_path": "runtime/price_model_coefficients.json"}
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        config.reinit_config()
        monkeypatch.setenv("ENERGY_OPTIMIZER_DEVIATION_RULES_PATH", str(rules_path))
        now = datetime(2026, 7, 5, 23, 0, tzinfo=_TZ)
        bundle = _sample_bundle(now)
        zip_path = write_capture_zip(
            bundle,
            current_soc=20.5,
            session_meta={"s2_cycle_offset": 0},
            captured_at=datetime(2026, 7, 5, 23, 0, 5),
        )
    assert zip_path.endswith("chart_debug_20260705_230005.zip")
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "README.txt" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["live_soc_percent"] == 20.5
        assert manifest["display_rows"]
        assert "Simulierter SoC (%)" in manifest["display_rows"][0]
        assert manifest["session_meta"]["s2_cycle_offset"] == 0
        assert manifest["chart_context"] is not None
        assert "inputs/config.json" in names
        assert "inputs/deviation_rules.json" in names
        assert "inputs/price_model_coefficients.json" in names
        assert "inputs/cons_data_hourly.csv" in names
        assert manifest["resolved_paths"]["config_json"].endswith("config.json")
        assert manifest["resolved_paths"]["deviation_rules_json"].endswith(
            "deviation_rules.json"
        )
        assert manifest["resolved_paths"]["forecast_model_path"].endswith(
            "price_model_coefficients.json"
        )
        assert manifest["resolved_paths"]["cons_data_path"].endswith(
            "cons_data_hourly.csv"
        )
        assert "inputs/config.json" in manifest["included_input_files"]
        assert "inputs/price_model_coefficients.json" in manifest["included_input_files"]
        assert "ENERGY_OPTIMIZER_CONFIG_PATH" in manifest["env_overrides"]


def test_build_capture_payload_json_safe(tmp_path, monkeypatch):
    with _chart_debug_config(tmp_path, monkeypatch, enabled=True):
        now = datetime(2026, 7, 5, 23, 0, tzinfo=_TZ)
        bundle = OptimizationDisplayBundle(
            savings_info={},
            baseline_df=pd.DataFrame(),
            display_df=pd.DataFrame([{"slot_datetime": now, "Simulierter SoC (%)": 19.0}]),
            display_matched=None,
            savings_view={},
            table_df=pd.DataFrame(),
            table_qualities=None,
            table_gap_notice=None,
            chart_context=None,
            chart_zones=None,
            sun_markers=None,
            chart_qualities=None,
            history_slot_count=None,
            matched_cost=None,
            optimized_cost=None,
            chart_header_label=None,
            chart_header_help=None,
            slot_deviation_events=(),
            simulation_table_title=None,
        )
        payload = build_capture_payload(
            bundle,
            current_soc=19.0,
            live_power=None,
            session_meta=None,
            chart1_plotly_json=None,
        )
    assert payload["live_soc_percent"] == 19.0
