"""Tests for runtime_store.config_load."""
from __future__ import annotations

import pytest


def test_load_config_or_exit_missing_path(tmp_path, monkeypatch, capsys):
    """Missing config.json must SystemExit before importing config.

    Do not unload sys.modules['config']: that leaves every already-imported
    ``import config`` binding pointing at a stale module while the next
    ``import config`` creates a new one — sequential suites then fail when
    monkeypatch patches the stale binding (e.g. test_shadow_feed).
    """
    missing = tmp_path / "missing" / "config.json"
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(missing))

    from runtime_store import config_load

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
