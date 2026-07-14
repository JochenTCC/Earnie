#!/usr/bin/env python3
"""Deploy silent-migration-test config/runtime to NAS earnie folder (2.0 cutover)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "silent-migration-test"
DEFAULT_NAS_ROOT = Path(r"\\DS-KO-DO-2\docker\earnie")

_CONFIG_FILES = (
    "config.json",
    "config.example.json",
    "components.json",
    "house_profiles.json",
    "backtesting_scenarios.json",
    "tariffs.json",
    "deviation_rules.json",
    "config.schema.json",
    "components.schema.json",
    "tariffs.schema.json",
    "house_profiles.schema.json",
    "backtesting_scenarios.schema.json",
    "deviation_rules.schema.json",
)

_RUNTIME_FILES = (
    "cons_data_hourly.csv",
    "cons_data_hourly.meta.json",
    "flexible_consumers_state.json",
    "pv_counter_state.json",
    "cons_data_pending.json",
    "consumption_profiles.csv",
    "total_consumption_profiles.csv",
    "flexible_consumer_profiles.csv",
)


def _read_json(path: Path) -> dict:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Datei '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def _live_scenario_settings(scenarios_path: Path) -> dict:
    doc = _read_json(scenarios_path)
    for entry in doc.get("scenarios", []):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id", "")).strip() == "live":
            settings = entry.get("settings")
            return dict(settings) if isinstance(settings, dict) else {}
    return {}


def _validate_source(source: Path) -> list[str]:
    issues: list[str] = []
    config_dir = source / "config"
    if not (config_dir / "config.json").is_file():
        issues.append(f"Quelle fehlt: {config_dir / 'config.json'}")
        return issues
    if not (config_dir / "components.json").is_file():
        issues.append(f"Quelle fehlt: {config_dir / 'components.json'}")
    scenarios_path = config_dir / "backtesting_scenarios.json"
    if not scenarios_path.is_file():
        issues.append(f"Quelle fehlt: {scenarios_path}")
        return issues
    live = _live_scenario_settings(scenarios_path)
    for key in (
        "battery_id",
        "pv_system_id",
        "import_tariff_id",
        "export_tariff_id",
        "house_profile_id",
    ):
        if not str(live.get(key, "") or "").strip():
            issues.append(
                f"backtesting_scenarios.json Live-Szenario: '{key}' ist leer "
                "(Bootstrap-Minimaldatei? setup_silent_migration_test erneut ausführen)."
            )
    return issues


def _copy_file(src: Path, dest: Path, *, dry_run: bool) -> bool:
    if not src.is_file():
        return False
    if dry_run:
        print(f"  würde kopieren: {src.name} -> {dest}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  kopiert: {src.name}")
    return True


def _copy_uploads(source_config: Path, dest_config: Path, *, dry_run: bool) -> None:
    uploads_src = source_config / "uploads"
    if not uploads_src.is_dir():
        return
    uploads_dest = dest_config / "uploads"
    if dry_run:
        count = sum(1 for item in uploads_src.rglob("*") if item.is_file())
        if count:
            print(f"  würde uploads/ kopieren ({count} Datei(en))")
        return
    shutil.copytree(uploads_src, uploads_dest, dirs_exist_ok=True)
    print(f"  kopiert: uploads/ ({uploads_src})")


def deploy_to_nas(
    *,
    source: Path,
    nas_root: Path,
    copy_runtime: bool,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    source_config = source / "config"
    source_runtime = source / "runtime"
    dest_config = nas_root / "config"
    dest_runtime = nas_root / "runtime"

    copied_config: list[str] = []
    copied_runtime: list[str] = []

    repo_components_schema = ROOT / "config" / "components.schema.json"
    repo_config_example = ROOT / "config" / "config.example.json"

    for name in _CONFIG_FILES:
        src = source_config / name
        if not src.is_file() and name == "components.schema.json":
            src = repo_components_schema
        if not src.is_file() and name == "config.example.json":
            src = repo_config_example
        if _copy_file(src, dest_config / name, dry_run=dry_run):
            copied_config.append(name)

    _copy_uploads(source_config, dest_config, dry_run=dry_run)

    if copy_runtime:
        for name in _RUNTIME_FILES:
            if _copy_file(source_runtime / name, dest_runtime / name, dry_run=dry_run):
                copied_runtime.append(name)

    return copied_config, copied_runtime


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description=(
            "Kopiert silent-migration-test nach NAS (config/, optional runtime/). "
            "Überspringt config/.env auf dem Ziel."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Quellordner (Standard: {DEFAULT_SOURCE.name}/)",
    )
    parser.add_argument(
        "--nas-root",
        type=Path,
        default=DEFAULT_NAS_ROOT,
        help=f"NAS-Ziel (Standard: {DEFAULT_NAS_ROOT})",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Runtime-Dateien mitkopieren (cons_data, Zustands-JSONs, Profile)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen, nichts kopieren",
    )
    args = parser.parse_args(argv)

    issues = _validate_source(args.source)
    if issues:
        for item in issues:
            print(f"FEHLER: {item}", file=sys.stderr)
        return 1

    if not args.nas_root.is_dir():
        print(f"FEHLER: NAS-Ziel nicht erreichbar: {args.nas_root}", file=sys.stderr)
        return 1

    print(f"Deploy {args.source.resolve()} -> {args.nas_root}")
    print("Hinweis: config/.env auf der NAS wird nicht überschrieben.")
    copied_config, copied_runtime = deploy_to_nas(
        source=args.source,
        nas_root=args.nas_root,
        copy_runtime=args.runtime,
        dry_run=args.dry_run,
    )

    if not copied_config:
        print("FEHLER: Keine Config-Dateien kopiert.", file=sys.stderr)
        return 1

    print()
    print(f"Config: {len(copied_config)} Datei(en)")
    if args.runtime:
        print(f"Runtime: {len(copied_runtime)} Datei(en)")
    print()
    print("Wichtig: ghcr.io/jochentcc/earnie-energy:latest muss 2.0-Config unterstützen")
    print("(components.json, thermal_rc in house_profiles). Altes Image bricht mit:")
    print("  Abbruch: profiles ... type muss generic, thermal_annual oder ev sein.")
    print("  Abbruch: Unbekannte battery_id '...'.")
    print()
    print("Auf der NAS nach Deploy:")
    print("  docker compose -f compose.yaml pull")
    print("  docker compose -f compose.yaml up -d")
    print("  docker logs earnie-optimizer-worker --tail 80")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
