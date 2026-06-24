#!/usr/bin/env python3
"""
migrate_persist_layout.py – Einmalige Migration zum Layout config/ + runtime/.

Verschiebt persistente Dateien aus dem Projektroot nach config/ bzw. runtime/.
Bestehende Zieldateien werden nicht überschrieben.

Aufruf:
  python -m scripts.migrate_persist_layout          # Vorschau
  python -m scripts.migrate_persist_layout --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_RUNTIME_MOVES = (
    "cons_data_hourly.csv",
    "cons_data_hourly.meta.json",
    "flexible_consumers_state.json",
    "pv_counter_state.json",
    "cons_data_pending.json",
    "consumption_profiles.csv",
    "total_consumption_profiles.csv",
    "flexible_consumer_profiles.csv",
    "energy_optimizer.log",
    "system_history_log.csv",
    "pv_accuracy_log.csv",
)


def _root() -> Path:
    return Path.cwd()


def _config_dir() -> Path:
    return _root() / "config"


def _runtime_dir() -> Path:
    return _root() / "runtime"


def _config_target() -> Path:
    return _config_dir() / "config.json"


def _planned_moves() -> list[tuple[Path, Path]]:
    root = _root()
    config_target = _config_target()
    runtime_dir = _runtime_dir()
    moves: list[tuple[Path, Path]] = []
    source_config = root / "config.json"
    if source_config.is_file() and not config_target.is_file():
        moves.append((source_config, config_target))

    for name in _RUNTIME_MOVES:
        source = root / name
        target = runtime_dir / name
        if source.is_file() and not target.is_file():
            moves.append((source, target))
    return moves


def _update_path_cons_data(config_path: Path, *, apply: bool) -> str | None:
    if not config_path.is_file():
        return None
    data = json.loads(config_path.read_text(encoding="utf-8"))
    block = data.get("file_paths_battery_simulation")
    if not isinstance(block, dict):
        return None
    current = block.get("path_cons_data", "")
    if current in ("runtime/cons_data_hourly.csv", str(_runtime_dir() / "cons_data_hourly.csv")):
        return None
    if current not in ("cons_data_hourly.csv", "", "cons_data_hourly"):
        return None
    message = f"path_cons_data: {current!r} -> 'runtime/cons_data_hourly.csv'"
    if apply:
        block["path_cons_data"] = "runtime/cons_data_hourly.csv"
        config_path.write_text(
            json.dumps(data, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migration zu config/ + runtime/ Layout")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Verschieben und config.json anpassen (Standard: nur Vorschau)",
    )
    args = parser.parse_args(argv)

    moves = _planned_moves()
    config_source = _config_target() if _config_target().is_file() else _root() / "config.json"
    config_patch = _update_path_cons_data(config_source, apply=args.apply)

    if not moves and not config_patch:
        print("Keine Migration nötig – Layout ist bereits aktuell.")
        return 0

    mode = "Anwenden" if args.apply else "Vorschau"
    print(f"=== Migration ({mode}) ===\n")

    for source, target in moves:
        print(f"  {source.relative_to(_root())}  ->  {target.relative_to(_root())}")
    if config_patch:
        print(f"  {config_patch}")

    if not args.apply:
        print("\nZum Ausführen: python -m scripts.migrate_persist_layout --apply")
        return 0

    _config_dir().mkdir(parents=True, exist_ok=True)
    _runtime_dir().mkdir(parents=True, exist_ok=True)
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(target))
            print(f"Verschoben: {source.name}")
        except OSError as exc:
            print(f"Übersprungen ({source.name}): {exc}", file=sys.stderr)

    if config_patch:
        print(config_patch)
    print("\nFertig. Container-Compose: Mounts ./config und ./runtime verwenden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
