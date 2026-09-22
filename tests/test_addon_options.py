# tests/test_addon_options.py
from __future__ import annotations

import json
from pathlib import Path

from runtime_store import addon_options


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_noop_outside_addon_context(tmp_path, monkeypatch):
    monkeypatch.delenv("EARNIE_INSTALL_CONTEXT", raising=False)
    config_path = tmp_path / "config.json"
    _write_json(config_path, {"ehal": {"backend": "loxone", "adapter_id": "loxone-home"}})
    monkeypatch.setenv("EARNIE_ENV_PATH", str(tmp_path))
    # resolve_config_json_path uses env; also point options away
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    assert addon_options.apply_addon_options(config_just_created=True) is False
    assert _read_json(config_path)["ehal"]["backend"] == "loxone"


def test_fresh_seed_sets_ha_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    config_path = tmp_path / "config.json"
    options_path = tmp_path / "options.json"
    _write_json(
        config_path,
        {"ehal": {"backend": "loxone", "adapter_id": "loxone-home"}, "ui": {}, "system": {}},
    )
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    assert addon_options.apply_addon_options(config_just_created=True) is True
    payload = _read_json(config_path)
    assert payload["ehal"]["backend"] == "ha"
    assert payload["ehal"]["adapter_id"] == "earnie-hems"
    assert payload["ehal"]["ha"].get("base_url", "") == ""
    assert payload["ehal"]["ha"].get("token", "") == ""


def test_existing_loxone_config_not_force_switched(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    config_path = tmp_path / "config.json"
    options_path = tmp_path / "options.json"
    _write_json(
        config_path,
        {"ehal": {"backend": "loxone", "adapter_id": "loxone-home"}, "ui": {}, "system": {}},
    )
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    assert addon_options.apply_addon_options(config_just_created=False) is False
    assert _read_json(config_path)["ehal"]["backend"] == "loxone"


def test_port_merge_from_options(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    config_path = tmp_path / "config.json"
    options_path = tmp_path / "options.json"
    _write_json(
        config_path,
        {
            "ehal": {"backend": "ha", "adapter_id": "earnie-hems"},
            "ui": {"streamlit_port": 8501},
            "system": {"ehal_loxone_http_port": 8541},
        },
    )
    _write_json(options_path, {"streamlit_port": 8511, "ehal_loxone_http_port": 8551})
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    assert addon_options.apply_addon_options(config_just_created=False) is True
    payload = _read_json(config_path)
    assert payload["ui"]["streamlit_port"] == 8511
    assert payload["system"]["ehal_loxone_http_port"] == 8551
    assert payload["ehal"]["backend"] == "ha"
