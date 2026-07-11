"""Tests für den Roh-JSON-Editor der Konfigurations-Seite (reine Logik)."""
from __future__ import annotations

import json
from pathlib import Path

from runtime_store.persist_paths import resolve_config_json_path
from ui.pages import page_config


def test_validate_text_rejects_invalid_json():
    data, error = page_config._validate_text("{ das ist kein json ")
    assert data is None
    assert error is not None
    assert "Ungültiges JSON" in error


def test_validate_text_accepts_fixture_config():
    text = Path(resolve_config_json_path()).read_text(encoding="utf-8")
    data, error = page_config._validate_text(text)
    assert error is None
    assert isinstance(data, dict)


def test_validate_text_reports_schema_violation():
    data, error = page_config._validate_text('{"system": 5}')
    assert data is None
    assert error is not None
    assert "Schema-Verletzung" in error


def test_save_text_writes_atomically(tmp_path):
    target = tmp_path / "config" / "config.json"
    page_config._save_text(str(target), '{"a": 1}\n')
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert not target.with_suffix(".json.tmp").exists()


def test_read_config_text_roundtrip(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"x": 2}\n', encoding="utf-8")
    assert page_config._read_config_text(str(target)) == '{"x": 2}\n'
