# tests/test_bootstrap_runtime.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_store import bootstrap


def test_bootstrap_creates_missing_files_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")

    (tmp_path / "config.example.json").write_text(
        json.dumps({"awattar": {"url": "https://example.test"}}),
        encoding="utf-8",
    )

    bootstrap.run()

    config_path = tmp_path / "config" / "config.json"
    cons_data_path = tmp_path / "runtime" / "cons_data_hourly.csv"
    assert config_path.is_file()
    assert cons_data_path.is_file()
    assert json.loads(config_path.read_text(encoding="utf-8"))["awattar"]["url"] == "https://example.test"

    original_cons_data = "timestamp;total_kw;baseload_kw;pv_kw;source\n2020-01-01 00:00:00;1;1;0;measured\n"
    cons_data_path.write_text(original_cons_data, encoding="utf-8")

    bootstrap.run()

    assert cons_data_path.read_text(encoding="utf-8") == original_cons_data


def test_bootstrap_rejects_directory_instead_of_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    (tmp_path / "config.example.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").mkdir()

    with pytest.raises(bootstrap.BootstrapError, match="Verzeichnis"):
        bootstrap.run()
