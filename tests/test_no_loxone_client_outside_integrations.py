"""Guard: production code outside integrations/ must not import Loxone I/O modules."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_MODULES = frozenset(
    {
        "integrations.loxone_client",
        "integrations.loxone_writes",
        "integrations.loxone_live_power",
    }
)

SCAN_DIRS = (
    "optimizer",
    "data",
    "runtime_store",
    "ui",
    "settings",
    "house_config",
    "simulation",
)
SCAN_FILES = ("main.py",)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
    return found


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for name in SCAN_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    for dirname in SCAN_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def test_no_loxone_io_imports_outside_integrations():
    violations: list[str] = []
    for path in _iter_py_files():
        imported = _imported_modules(path)
        bad = sorted(imported & FORBIDDEN_MODULES)
        if not bad:
            continue
        rel = path.relative_to(ROOT).as_posix()
        violations.append(f"{rel}: {', '.join(bad)}")
    assert not violations, (
        "Use integrations.ehal_live for live I/O; forbidden imports:\n"
        + "\n".join(violations)
    )
