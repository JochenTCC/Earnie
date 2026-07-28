# tests/test_ehal_connection.py
from __future__ import annotations

import json

from ui import ehal_connection


def test_persist_ehal_backend_writes_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "ui.house_config_io.resolve_config_json_path", lambda: str(config_path)
    )
    monkeypatch.setattr(
        ehal_connection, "reset_adapter_cache", lambda: None
    )
    monkeypatch.setattr(
        "ui.house_config_io.config.reinit_config", lambda **kwargs: None
    )

    ehal_connection.persist_ehal_backend("ha")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["ehal"]["backend"] == "ha"

    ehal_connection.persist_ehal_backend("loxone")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["ehal"]["backend"] == "loxone"
