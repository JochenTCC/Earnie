"""Thin wrapper: run pytest with the active interpreter (pre-commit / agent entry point).

When pytest-xdist is installed and the caller did not already choose a worker
count, defaults to ``-n auto`` for multi-CPU runs. Pass ``-n 0`` or ``-n 1``
for sequential execution (debugging, --dead-fixtures, mutmut).

Runs go through the machine-wide test queue (``scripts.suite_queue``): parallel
agent sessions and git hooks wait for each other instead of overloading the CPU.

* **Queued** (default): no explicit target, any directory target (``tests``),
  or anything the wrapper cannot classify.
* **Fast lane** (no queue, ``-n 2`` default): at most ``FAST_LANE_MAX_TARGETS``
  explicit test files / node ids (``tests/test_x.py``, ``tests/test_x.py::test_y``)
  and no directory. ``--collect-only`` / ``--dead-fixtures`` also skip the queue.
* ``--queue`` forces queueing, ``--no-queue`` skips it (wrapper flags, not
  passed to pytest). ``EARNIE_TEST_QUEUE=off`` disables the queue entirely.
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

FAST_LANE_MAX_TARGETS = 3
FAST_LANE_WORKERS = "2"

# pytest options whose value is a separate argv entry (so it is not a target).
_OPTIONS_WITH_VALUE = frozenset(
    {
        "-k",
        "-m",
        "-n",
        "-p",
        "-c",
        "-o",
        "-W",
        "-r",
        "--numprocesses",
        "--maxfail",
        "--junitxml",
        "--junit-xml",
        "--basetemp",
        "--deselect",
        "--ignore",
        "--ignore-glob",
        "--rootdir",
        "--confcutdir",
        "--tb",
        "--durations",
        "--cov",
        "--cov-report",
        "--dist",
        "--maxprocesses",
        "--log-level",
        "--override-ini",
        "--import-mode",
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


def _targets(args: list[str]) -> list[str]:
    """Positional pytest arguments (paths / node ids), skipping option values."""
    targets: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("-"):
            if arg in _OPTIONS_WITH_VALUE:
                skip_next = True
            continue
        targets.append(arg)
    return targets


def _is_fast_lane(args: list[str], root: Path = ROOT) -> bool:
    """True for a small, explicit selection of test files / node ids."""
    targets = _targets(args)
    if not targets or len(targets) > FAST_LANE_MAX_TARGETS:
        return False
    for target in targets:
        path = root / target.split("::", 1)[0]
        if not path.is_file() or path.suffix != ".py":
            return False
    return True


def _split_queue_flags(args: list[str]) -> tuple[list[str], bool | None]:
    """Strip wrapper-only ``--queue`` / ``--no-queue``; return (args, forced)."""
    forced: bool | None = None
    rest: list[str] = []
    for arg in args:
        if arg == "--queue":
            forced = True
        elif arg == "--no-queue":
            forced = False
        else:
            rest.append(arg)
    return rest, forced


def _should_queue(args: list[str], forced: bool | None, root: Path = ROOT) -> bool:
    if forced is not None:
        return forced
    if any(flag in args for flag in _SEQUENTIAL_FLAGS):
        return False
    return not _is_fast_lane(args, root)


def _label(args: list[str]) -> str:
    shown = " ".join(args)
    if len(shown) > 120:
        shown = shown[:117] + "..."
    return f"pytest {shown} [{ROOT.name}]"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    args, forced = _split_queue_flags(args)
    if not args:
        args = ["tests", "-q", "--tb=short"]
    queued = _should_queue(args, forced)
    if _should_default_parallel(args):
        workers = "auto" if queued or forced is False else FAST_LANE_WORKERS
        args = ["-n", workers, *args]
    cmd = [sys.executable, "-m", "pytest", *args]
    if not queued:
        return subprocess.call(cmd, cwd=ROOT)

    from scripts.suite_queue import queued_slot

    with queued_slot(_label(args)):
        return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
