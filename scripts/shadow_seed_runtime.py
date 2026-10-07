"""Seed a Shadow runtime directory from Prod learned state (§6.5)."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_COPY_NAMES = (
    "optimization_history.jsonl",
    "pv_counter_state.json",
    "power_interval_sampler_state.json",
    "flexible_consumers_state.json",
    "optimizer_run_state.json",
    "live_optimization_debug.json",
)

_COPY_GLOBS = (
    "cons_data*.csv",
    "consumption_profiles*",
)

_EXCLUDE_NAMES = frozenset(
    {
        "earnie.log",
        "local_settings.json",
        "ehal_write_error.json",
        "main.lock",
        "main.pid",
        "loxone_auth_error.json",
    }
)


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def seed_runtime(*, src: Path, dst: Path) -> list[str]:
    """Copy learned/state files from *src* to *dst*. Returns copied paths."""
    if not src.is_dir():
        raise FileNotFoundError(f"source runtime not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    for name in _COPY_NAMES:
        if name in _EXCLUDE_NAMES:
            continue
        source = src / name
        if not source.is_file():
            continue
        target = dst / name
        shutil.copy2(source, target)
        copied.append(str(target))

    # Monthly archives of the production history (same stem + stamped suffix).
    for source in sorted(src.glob("optimization_history.jsonl.*")):
        if not source.is_file() or source.name in _EXCLUDE_NAMES:
            continue
        target = dst / source.name
        shutil.copy2(source, target)
        copied.append(str(target))

    for pattern in _COPY_GLOBS:
        for source in src.glob(pattern):
            if source.name in _EXCLUDE_NAMES:
                continue
            if source.name.startswith("earnie.log"):
                continue
            if source.suffix == ".lock" or source.suffix == ".pid":
                continue
            target = dst / source.name
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            copied.append(str(target))

    marker = dst / ".shadow_runtime"
    if not marker.is_file():
        marker.write_text("shadow\n", encoding="utf-8")
        copied.append(str(marker))
    return copied


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Seed Shadow runtime from Prod (profiles, cons_data, history). "
            "Excludes logs, locks, local_settings.json."
        )
    )
    parser.add_argument(
        "--from",
        dest="src",
        required=True,
        help="Prod runtime directory",
    )
    parser.add_argument(
        "--to",
        dest="dst",
        required=True,
        help="Shadow runtime directory",
    )
    args = parser.parse_args(argv)
    src = Path(args.src)
    dst = Path(args.dst)
    try:
        copied = seed_runtime(src=src, dst=dst)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"Seeded {len(copied)} path(s) into {dst}")
    for path in copied:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
