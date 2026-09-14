"""Thin wrapper: run pytest with the active interpreter (pre-commit / agent entry point)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        args = ["tests", "-q", "--tb=short"]
    cmd = [sys.executable, "-m", "pytest", *args]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
