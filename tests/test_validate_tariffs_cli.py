# tests/test_validate_tariffs_cli.py
from __future__ import annotations

from pathlib import Path

from scripts import validate_tariffs as vt


def test_validate_tariffs_cli_ok_on_repo_catalog():
    root = Path(__file__).resolve().parents[1]
    code = vt.main(
        [
            "--tariffs",
            str(root / "config" / "tariffs.json"),
            "--schema",
            str(root / "config" / "tariffs.schema.json"),
            "--skip-scenarios",
            "--check-catalog",
            "--import-json",
            str(root / "stromtarife_dach_kombiniert.json"),
            "--export-json",
            str(root / "einspeisetarife_dach_erweitert.json"),
        ]
    )
    assert code == 0


def test_validate_tariffs_cli_fails_on_missing_file(tmp_path):
    missing = tmp_path / "missing.json"
    code = vt.main(["--tariffs", str(missing), "--skip-scenarios", "--skip-schema"])
    assert code == 1
