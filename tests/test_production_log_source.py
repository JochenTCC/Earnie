"""Tests für Produktiv-Log-Datenbasis (UI-Caption)."""
from __future__ import annotations

from datetime import datetime

from runtime_store import optimization_history
from ui.simulation_results import (
    format_display_data_basis_caption,
    format_display_data_basis_path,
)


def test_describe_production_log_source(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    history = runtime / "optimization_history.jsonl"
    history.write_text('{"completed_at": "2026-07-04T09:00:00"}\n', encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(
        optimization_history,
        "RUNTIME_DIR",
        str(runtime),
    )
    monkeypatch.setattr(
        optimization_history,
        "HISTORY_FILE",
        str(history),
    )
    info = optimization_history.describe_production_log_source()
    assert info.history_exists
    assert info.history_file == str(history.resolve())
    assert info.env_runtime_dir == str(runtime)


def test_format_display_data_basis_path():
    info = optimization_history.ProductionLogSourceInfo(
        runtime_dir=r"C:\data\runtime",
        env_runtime_dir=r"\\nas\runtime",
        history_file=r"\\nas\runtime\optimization_history.jsonl",
        history_exists=True,
        history_size_bytes=1200,
        history_modified_at=datetime(2026, 7, 4, 19, 0, 0),
        legacy_csv_file=r"C:\legacy.csv",
        legacy_csv_exists=False,
    )
    assert format_display_data_basis_path(info) == r"\\nas\runtime\optimization_history.jsonl"


def test_format_display_data_basis_caption_merge_active():
    info = optimization_history.ProductionLogSourceInfo(
        runtime_dir=r"C:\data\runtime",
        env_runtime_dir=r"\\nas\runtime",
        history_file=r"\\nas\runtime\optimization_history.jsonl",
        history_exists=True,
        history_size_bytes=1200,
        history_modified_at=datetime(2026, 7, 4, 19, 0, 0),
        legacy_csv_file=r"C:\legacy.csv",
        legacy_csv_exists=False,
    )
    text = format_display_data_basis_caption(
        info,
        merge_active=True,
        history_slot_count=55,
    )
    assert "Merge-Pfad aktiv" in text
    assert "optimization_history.jsonl" in text
    assert "55 Viertelstunden-Slots" in text
    assert "consumer_powers_kw" in text


def test_format_display_data_basis_caption_no_merge():
    info = optimization_history.ProductionLogSourceInfo(
        runtime_dir="/tmp/runtime",
        env_runtime_dir=None,
        history_file="/tmp/runtime/optimization_history.jsonl",
        history_exists=False,
        history_size_bytes=None,
        history_modified_at=None,
        legacy_csv_file="/tmp/legacy.csv",
        legacy_csv_exists=False,
    )
    text = format_display_data_basis_caption(info, merge_active=False)
    assert "Kein Merge-Pfad" in text
    assert "nicht gefunden" in text
