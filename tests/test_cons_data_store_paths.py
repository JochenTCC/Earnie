"""Pfadauflösung für cons_data_hourly.csv."""
from __future__ import annotations

from unittest.mock import patch

from data import cons_data_store
from runtime_store.persist_paths import resolve_runtime_prefixed_path


def test_resolve_runtime_prefixed_path_uses_runtime_dir(monkeypatch, tmp_path):
    nas_runtime = tmp_path / "nas_runtime"
    nas_runtime.mkdir()
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(nas_runtime))

    resolved = resolve_runtime_prefixed_path("runtime/cons_data_hourly.csv")

    assert resolved == str(nas_runtime / "cons_data_hourly.csv")


def test_resolve_runtime_prefixed_path_keeps_fixture_paths():
    fixture = "tests/fixtures/backtesting/cons_data_hourly.csv"
    assert resolve_runtime_prefixed_path(fixture) == fixture


def test_get_output_path_uses_runtime_dir_for_standard_config(monkeypatch, tmp_path):
    nas_runtime = tmp_path / "nas_runtime"
    nas_runtime.mkdir()
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(nas_runtime))

    with patch.object(
        cons_data_store.config,
        "get_file_paths_battery_simulation",
        return_value={"path_cons_data": "runtime/cons_data_hourly.csv"},
    ):
        assert cons_data_store.get_output_path() == str(nas_runtime / "cons_data_hourly.csv")
