"""Tests für runtime_store.config_load."""
from __future__ import annotations

import importlib
import sys

import pytest


def _unload_config_modules() -> None:
    for name in list(sys.modules):
        if name == "config" or name.startswith("config."):
            del sys.modules[name]


def test_load_config_or_exit_missing_path(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "missing" / "config.json"
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(missing))
    _unload_config_modules()

    from runtime_store import config_load

    importlib.reload(config_load)

    with pytest.raises(SystemExit) as exc:
        config_load.load_config_or_exit()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Konfigurationsdatei nicht gefunden" in err
    assert "missing" in err
    assert "config.json" in err


def test_reinit_config_or_exit_propagates_validation_error(capsys):
    from runtime_store import config_load

    class _FakeConfig:
        def reinit_config(self, **kwargs):
            raise ValueError("Block 'awattar' in config.json ist entfernt")

    with pytest.raises(SystemExit) as exc:
        config_load.reinit_config_or_exit(_FakeConfig())

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "awattar" in err
