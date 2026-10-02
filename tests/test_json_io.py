"""Regression: invalid config JSON must name file + line/column (bootstrap stamp)."""
from __future__ import annotations

import pytest

from settings.json_io import read_json_dict


def test_read_json_dict_invalid_json_includes_path_and_line(tmp_path):
    """Missing comma must not surface as bare JSONDecodeError without path."""
    path = tmp_path / "config.json"
    path.write_text(
        '{\n  "batteries": []\n  "pv_systems": []\n}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"ungültiges JSON \(Zeile 3, Spalte 3\)") as exc_info:
        read_json_dict(str(path))
    msg = str(exc_info.value)
    assert str(path) in msg
    assert "Expecting ',' delimiter" in msg


def test_bootstrap_run_invalid_config_json_exits_without_traceback(
    tmp_path, monkeypatch, capsys
):
    """bootstrap.run must abort like load_config_or_exit (SystemExit, no raise)."""
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (tmp_path / "runtime").mkdir()
    bad = config_dir / "config.json"
    bad.write_text(
        '{\n  "batteries": []\n  "pv_systems": []\n}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(bad))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))

    from runtime_store import bootstrap

    with pytest.raises(SystemExit) as exc_info:
        bootstrap.run()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Abbruch:" in err
    assert "ungültiges JSON" in err
    assert str(bad) in err
