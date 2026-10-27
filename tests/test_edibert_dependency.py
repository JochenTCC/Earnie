# tests/test_edibert_dependency.py
"""Edibert P0: the tariff library is installed and its licence travels with it."""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pinned_tag() -> str:
    deps = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    edibert = [d for d in deps if re.match(r"edibert(\[[^\]]*\])? @", d)]
    assert len(edibert) == 1, f"expected one edibert pin in pyproject.toml, got {edibert}"
    match = re.search(r"/archive/refs/tags/v(?P<version>[^/]+)\.zip$", edibert[0])
    assert match, f"edibert must be pinned to a tag archive: {edibert[0]}"
    return match["version"]


def test_import_edibert():
    import edibert

    assert edibert.__version__


def test_installed_edibert_matches_pin():
    # An editable sibling checkout (pip install -e ../Edibert) may be ahead of the pin, never behind.
    pinned = tuple(int(p) for p in _pinned_tag().split("."))
    installed = metadata.version("edibert")
    installed_parts = tuple(int(p) for p in re.findall(r"\d+", installed)[:3])
    assert installed_parts >= pinned, f"installed edibert {installed} is older than the pin {_pinned_tag()}"


def test_edibert_ships_license_and_notice():
    files = {Path(f.name).name for f in metadata.files("edibert") or ()}
    assert {"LICENSE", "NOTICE"} <= files, f"edibert distribution lacks LICENSE/NOTICE: {sorted(files)}"
