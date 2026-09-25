"""HouseSim S4 packaging: core/fixtures sync equality and import isolation."""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from scripts.sync_house_sim_integration import (
    CHECKSUM_NAME,
    DEST_CORE,
    DEST_FIXTURES,
    DEST_ROOT,
    SRC_CORE,
    SRC_FIXTURES,
    _rel_files,
    _sha256,
    sync,
)

FORBIDDEN_ROOTS = frozenset(
    {
        "homeassistant",
        "optimizer",
        "integrations",
        "house_config",
        "ehal",
        "runtime_store",
        "data",
        "ui",
        "simulation",
        "settings",
    }
)

SYNC_HINT = (
    "house_sim core/fixtures copy is out of sync. Run: "
    "python -m scripts.sync_house_sim_integration"
)


def _module_roots_from_import(node: ast.AST) -> set[str]:
    roots: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            roots.add(alias.name.split(".", 1)[0])
    elif isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return roots
        if node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _forbidden_imports_in_tree(root: Path) -> list[str]:
    hits: list[str] = []
    for path in _rel_files(root):
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for name in _module_roots_from_import(node):
                if name in FORBIDDEN_ROOTS:
                    hits.append(f"{path.relative_to(root).as_posix()}: import {name}")
    return hits


def test_sync_keeps_core_and_fixtures_equal():
    sync()
    assert DEST_CORE.is_dir(), SYNC_HINT
    assert DEST_FIXTURES.is_dir(), SYNC_HINT
    checksum_path = DEST_ROOT / CHECKSUM_NAME
    assert checksum_path.is_file(), SYNC_HINT
    recorded = json.loads(checksum_path.read_text(encoding="utf-8"))

    src_core = {
        p.relative_to(SRC_CORE).as_posix(): _sha256(p) for p in _rel_files(SRC_CORE)
    }
    src_fix = {
        p.relative_to(SRC_FIXTURES).as_posix(): _sha256(p)
        for p in _rel_files(SRC_FIXTURES)
    }
    assert set(src_core) == set(recorded["core"]), SYNC_HINT
    assert set(src_fix) == set(recorded["fixtures"]), SYNC_HINT
    for rel, digest in src_core.items():
        assert recorded["core"][rel] == digest, SYNC_HINT
        dest = DEST_CORE / rel
        assert dest.is_file(), SYNC_HINT
        # Dest may have GENERATED header; compare source checksums only.
    for rel, digest in src_fix.items():
        assert recorded["fixtures"][rel] == digest, SYNC_HINT
        assert (DEST_FIXTURES / rel).is_file(), SYNC_HINT

    dest_core_rels = {
        p.relative_to(DEST_CORE).as_posix() for p in _rel_files(DEST_CORE)
    }
    dest_fix_rels = {
        p.relative_to(DEST_FIXTURES).as_posix() for p in _rel_files(DEST_FIXTURES)
    }
    assert dest_core_rels == set(src_core), SYNC_HINT
    assert dest_fix_rels == set(src_fix), SYNC_HINT


def test_core_imports_neither_homeassistant_nor_earnie():
    hits = _forbidden_imports_in_tree(SRC_CORE)
    assert hits == [], f"Forbidden imports in house_sim/core: {hits}"
    if DEST_CORE.is_dir():
        hits_copy = _forbidden_imports_in_tree(DEST_CORE)
        assert hits_copy == [], f"Forbidden imports in _core copy: {hits_copy}"


def test_core_package_imports():
    mod = importlib.import_module("house_sim.core")
    assert hasattr(mod, "step_physics")
    assert hasattr(mod, "pv_kw_from_weather")
    assert hasattr(mod, "simulate_next_temp_c")
