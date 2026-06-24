# tests/test_migrate_persist_layout.py
from __future__ import annotations

import json
from pathlib import Path

from scripts import migrate_persist_layout as migrate


def test_migrate_preview_lists_planned_moves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cons_data_hourly.csv").write_text("header\n", encoding="utf-8")

    moves = migrate._planned_moves()
    sources = {source.name for source, _ in moves}

    assert "config.json" in sources
    assert "cons_data_hourly.csv" in sources


def test_migrate_apply_moves_and_updates_path_cons_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_data = {
        "file_paths_battery_simulation": {"path_cons_data": "cons_data_hourly.csv"},
    }
    (tmp_path / "config.json").write_text(json.dumps(config_data), encoding="utf-8")

    assert migrate.main(["--apply"]) == 0

    assert (tmp_path / "config" / "config.json").is_file()
    assert not (tmp_path / "config.json").exists()
    updated = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
    assert updated["file_paths_battery_simulation"]["path_cons_data"] == "runtime/cons_data_hourly.csv"
