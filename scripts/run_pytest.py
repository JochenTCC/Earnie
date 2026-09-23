"""Thin wrapper: run pytest with the active interpreter (pre-commit / agent entry point).

When pytest-xdist is installed and the caller did not already choose a worker
count, defaults to ``-n auto`` for multi-CPU runs. Pass ``-n 0`` or ``-n 1``
for sequential execution (debugging, --dead-fixtures, mutmut).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEQUENTIAL_FLAGS = frozenset(
    {
        "--dead-fixtures",
        "--collect-only",
    }
)


def _has_numprocesses_flag(args: list[str]) -> bool:
    for arg in args:
        if arg in ("-n", "--numprocesses"):
            return True
        if arg.startswith("-n") and arg != "-n":
            # -nauto / -n4
            return True
        if arg.startswith("--numprocesses="):
            return True
    return False

def _should_default_parallel(args: list[str]) -> bool:
    if _has_numprocesses_flag(args):
        return False
    if any(flag in args for flag in _SEQUENTIAL_FLAGS):
        return False
    try:
        import xdist  # noqa: F401
    except ImportError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        args = ["tests", "-q", "--tb=short"]
    if _should_default_parallel(args):
        args = ["-n", "auto", *args]
    cmd = [sys.executable, "-m", "pytest", *args]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
