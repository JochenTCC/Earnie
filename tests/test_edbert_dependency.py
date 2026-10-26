# tests/test_edbert_dependency.py
"""Edbert P0: the tariff library is installed and its licence travels with it."""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pinned_tag() -> str:
    deps = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    edbert = [d for d in deps if d.startswith("edbert ")]
    assert len(edbert) == 1, f"expected one edbert pin in pyproject.toml, got {edbert}"
    match = re.search(r"/archive/refs/tags/v(?P<version>[^/]+)\.zip$", edbert[0])
    assert match, f"edbert must be pinned to a tag archive: {edbert[0]}"
    return match["version"]


def test_import_edbert():
    import edbert

    assert edbert.__version__


def test_installed_edbert_matches_pin():
    # An editable sibling checkout (pip install -e ../edbert) may be ahead of the pin, never behind.
    pinned = tuple(int(p) for p in _pinned_tag().split("."))
    installed = metadata.version("edbert")
    installed_parts = tuple(int(p) for p in re.findall(r"\d+", installed)[:3])
    assert installed_parts >= pinned, f"installed edbert {installed} is older than the pin {_pinned_tag()}"


def test_edbert_ships_license_and_notice():
    files = {Path(f.name).name for f in metadata.files("edbert") or ()}
    assert {"LICENSE", "NOTICE"} <= files, f"edbert distribution lacks LICENSE/NOTICE: {sorted(files)}"
