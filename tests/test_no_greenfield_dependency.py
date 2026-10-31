"""Guard: tests must not read the local, gitignored ``greenfield/`` pack.

``greenfield/`` is a per-machine dogfood tree (see ``.gitignore``); tests that read it
pass or skip depending on whose checkout runs them. Use checked-in fixtures under
``tests/fixtures/`` or build the tree under ``tmp_path`` instead.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
DIRNAME = "greenfield"


def _division_root(node: ast.expr) -> ast.expr:
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        node = node.left
    return node


def _greenfield_refs(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        # Path("greenfield/config/...") or open("greenfield\\...")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith((DIRNAME + "/", DIRNAME + "\\"))
        ):
            lines.append(node.lineno)
        # repo_root / "greenfield" / ... (tmp_path / "greenfield" is fine)
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and node.right.value == DIRNAME
            and "tmp" not in ast.unparse(_division_root(node.left))
        ):
            lines.append(node.lineno)
    return lines


def test_tests_do_not_read_local_greenfield_pack():
    this_file = Path(__file__).resolve()
    violations: list[str] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.resolve() == this_file:
            continue
        rel = path.relative_to(ROOT).as_posix()
        violations.extend(f"{rel}:{line}" for line in _greenfield_refs(path))
    assert not violations, (
        "Tests must not depend on the local greenfield/ pack; use tests/fixtures/ "
        "or tmp_path:\n" + "\n".join(violations)
    )
