"""Tests for unified debug-dump archive (schema v2) and replay helper."""
from __future__ import annotations

import json
import os
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import config
from runtime_store.chart_debug_capture import write_capture_zip
from runtime_store.debug_dump_archive import (
    DUMP_SCHEMA_VERSION,
    DUMP_TYPE_CHART,
    DUMP_TYPE_PROD,
    normalize_manifest,
    validate_dump_layout,
    write_debug_dump_zip,
)
from scripts import archive_prod_dump as archive_script
from scripts.replay_debug_dump import replay_debug_dump
from ui.chart_context import build_live_chart_context
from ui.simulation_results import build_optimization_display_bundle

from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree

_TZ = ZoneInfo("Europe/Vienna")
_CONFIG_ENV_KEYS = (
    "ENERGY_OPTIMIZER_CONFIG_PATH",
    "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
    "ENERGY_OPTIMIZER_OFFLINE",
    "ENERGY_OPTIMIZER_RUNTIME_DIR",
    "ENERGY_OPTIMIZER_UI_CHART_DEBUG_CAPTURE_ENABLED",
    "ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH",
)


@contextmanager
def _dump_config(tmp_path, monkeypatch):
    prev = {key: os.environ.get(key) for key in _CONFIG_ENV_KEYS}
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_CHART_DEBUG_CAPTURE_ENABLED", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(
            extra={
                "ui": {
                    "chart_debug_capture_enabled": True,
                    "chart_debug_capture_dir": "chart_debug",
                }
            }
        ),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", config_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH", scenarios_path)
    config.reinit_config()
    try:
        yield
    finally:
        for key, value in prev.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        config.reinit_config()


def _sample_bundle(now: datetime):
    chart_context = build_live_chart_context(0, 0, now=now)
    savings_info = {
        "optimized_cost_euro": 1.0,
        "matched_baseline_cost_euro": 1.2,
        "savings_matched_euro": 0.2,
        "optimized_rows": [],
        "baseline_rows": [],
    }
    optimized_df = pd.DataFrame(
        [
            {
                "slot_datetime": chart_context.chart_window.start,
                "Uhrzeit": chart_context.chart_window.start.strftime("%d.%m. %H:%M"),
                "Simulierter SoC (%)": 42.0,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Preis extrapoliert": False,
            }
        ]
    )
    return build_optimization_display_bundle(
        savings_info,
        optimized_df,
        pd.DataFrame(),
        chart_context=chart_context,
        optimization_matrix=optimized_df.to_dict("records"),
    )


def test_write_prod_dump_zip_requires_history(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        try:
            write_debug_dump_zip(
                DUMP_TYPE_PROD,
                title="t",
                symptom="s",
                captured_at=datetime(2026, 7, 16, 8, 0, 0),
            )
            raised = False
        except FileNotFoundError:
            raised = True
    assert raised


def test_write_prod_dump_zip_ok(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "optimization_history.jsonl").write_text(
            '{"written_at":"2026-07-16T08:00:00","soc_percent":50}\n',
            encoding="utf-8",
        )
        (runtime / "optimizer_run_state.json").write_text(
            '{"ok":true}',
            encoding="utf-8",
        )
        zip_path = write_debug_dump_zip(
            DUMP_TYPE_PROD,
            title="EV miss",
            symptom="deadline",
            case_id="case_x",
            captured_at=datetime(2026, 7, 16, 8, 0, 0),
        )
    assert zip_path.endswith("debug_dump_prod_20260716_080000.zip")
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert "runtime/optimization_history.jsonl" in names
        assert "runtime/optimizer_run_state.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == DUMP_SCHEMA_VERSION
        assert manifest["dump_type"] == DUMP_TYPE_PROD
        assert manifest["prod"]["title"] == "EV miss"
        assert manifest["prod"]["symptom"] == "deadline"
        assert "runtime/optimization_history.jsonl" in manifest["files"][
            "required_present"
        ]
        assert "runtime/optimizer_run_state.json" in manifest["files"][
            "optional_present"
        ]


def test_normalize_manifest_v1_chart():
    raw = {
        "schema_version": 1,
        "captured_at": "2026-07-05T23:00:00",
        "live_soc_percent": 20.5,
        "display_rows": [{"Simulierter SoC (%)": 20.5}],
        "chart_context": {"now": "x"},
    }
    normalized = normalize_manifest(raw)
    assert normalized["dump_type"] == DUMP_TYPE_CHART
    assert normalized["chart"]["live_soc_percent"] == 20.5
    assert normalized["chart"]["display_rows"]


def test_replay_chart_dump(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        now = datetime(2026, 7, 5, 23, 0, tzinfo=_TZ)
        bundle = _sample_bundle(now)
        zip_path = write_capture_zip(
            bundle,
            current_soc=20.5,
            session_meta={"s2_cycle_offset": 0},
            captured_at=datetime(2026, 7, 5, 23, 0, 5),
        )
        extract = tmp_path / "extract_chart"
        rc = replay_debug_dump(Path(zip_path), keep_extract=extract)
    assert rc == 0
    validate_dump_layout(extract, dump_type=DUMP_TYPE_CHART)


def test_replay_prod_dump(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "optimization_history.jsonl").write_text(
            '{"written_at":"2026-07-16T08:00:00"}\n',
            encoding="utf-8",
        )
        zip_path = write_debug_dump_zip(
            DUMP_TYPE_PROD,
            title="t",
            symptom="s",
            captured_at=datetime(2026, 7, 16, 8, 0, 0),
        )
        extract = tmp_path / "extract_prod"
        rc = replay_debug_dump(Path(zip_path), keep_extract=extract)
    assert rc == 0


def test_archive_prod_dump_from_unified_zip(tmp_path, monkeypatch):
    with _dump_config(tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "optimization_history.jsonl").write_text(
            '{"written_at":"2026-07-16T08:00:00"}\n',
            encoding="utf-8",
        )
        zip_path = write_debug_dump_zip(
            DUMP_TYPE_PROD,
            title="from zip",
            symptom="captured",
            captured_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        monkeypatch.setattr(archive_script, "FIXTURES_ROOT", tmp_path / "fixtures")
        target = archive_script.archive_prod_dump(
            case_id="unified_zip_case",
            title="CLI title",
            symptom="CLI symptom",
            source=Path(zip_path),
            app_version="",
            recorded_at="2026-07-16",
            regression={},
            force=False,
        )
    assert (target / "optimization_history.jsonl").is_file()
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "unified_zip_case"
    assert manifest["title"] == "CLI title"
    assert "optimization_history.jsonl" in manifest["files"]
