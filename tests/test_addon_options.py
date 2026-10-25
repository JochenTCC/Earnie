# tests/test_addon_options.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert "base_url" not in payload["ehal"]["ha"]
    assert "token" not in payload["ehal"]["ha"]


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
            "system": {"ehal_http_port": 8541},
        },
    )
    _write_json(options_path, {"streamlit_port": 8511, "ehal_http_port": 8551})
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    assert addon_options.apply_addon_options(config_just_created=False) is True
    payload = _read_json(config_path)
    assert payload["ui"]["streamlit_port"] == 8511
    assert payload["system"]["ehal_http_port"] == 8551
    assert "ehal_loxone_http_port" not in payload["system"]
    assert payload["ehal"]["backend"] == "ha"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        # Supervisor fills the renamed option with its default; the old custom value wins.
        ({"ehal_http_port": 8541, "ehal_loxone_http_port": 8551}, 8551),
        ({"ehal_loxone_http_port": 8551}, 8551),
        # Once the new option holds a custom value, the legacy one is ignored.
        ({"ehal_http_port": 8560, "ehal_loxone_http_port": 8551}, 8560),
        ({"ehal_http_port": 8560}, 8560),
    ],
)
def test_ehal_http_port_option_carries_over_legacy_name(tmp_path, monkeypatch, options, expected):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    config_path = tmp_path / "config.json"
    options_path = tmp_path / "options.json"
    _write_json(
        config_path,
        {"ehal": {"backend": "ha", "adapter_id": "earnie-hems"}, "ui": {}, "system": {}},
    )
    _write_json(options_path, options)
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    assert addon_options.apply_addon_options(config_just_created=False) is True
    assert _read_json(config_path)["system"]["ehal_http_port"] == expected


def _no_ping_spawn(monkeypatch) -> None:
    """set_consent("on") → refresh_points may spawn a real ping; not under test here."""
    from runtime_store import usage_ping as up

    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: False)


def test_usage_ping_option_sets_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    _no_ping_spawn(monkeypatch)
    config_path = tmp_path / "config.json"
    options_path = tmp_path / "options.json"
    _write_json(
        config_path,
        {"ehal": {"backend": "ha", "adapter_id": "earnie-hems"}, "ui": {}, "system": {}},
    )
    _write_json(options_path, {"usage_ping": True})
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    from runtime_store import usage_ping as up

    assert addon_options.apply_addon_options(config_just_created=False) is False
    assert up.load_state()["consent"] == "on"
    assert up.load_state().get("install_id")

    _write_json(options_path, {"usage_ping": False})
    assert addon_options.apply_addon_options(config_just_created=False) is False
    assert up.load_state()["consent"] == "off"
    assert "install_id" not in up.load_state()


def test_usage_ping_option_absent_leaves_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    _no_ping_spawn(monkeypatch)
    config_path = tmp_path / "config.json"
    options_path = tmp_path / "options.json"
    _write_json(
        config_path,
        {"ehal": {"backend": "ha", "adapter_id": "earnie-hems"}, "ui": {}, "system": {}},
    )
    _write_json(options_path, {})
    monkeypatch.setattr(addon_options, "resolve_config_json_path", lambda: str(config_path))
    monkeypatch.setattr(addon_options, "options_path", lambda: str(options_path))
    from runtime_store import usage_ping as up

    up.set_consent("on")
    install_id = up.load_state()["install_id"]
    assert addon_options.apply_addon_options(config_just_created=False) is False
    state = up.load_state()
    assert state["consent"] == "on"
    assert state["install_id"] == install_id
