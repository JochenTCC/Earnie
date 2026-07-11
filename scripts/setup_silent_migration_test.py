#!/usr/bin/env python3
"""Erzeugt silent-migration-test/ mit vollständiger P5+P6-Migration aus NAS-Config."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from house_config.migrate_runtime_entities import (
    finalize_migration_for_2_0,
    migrate_runtime_entities,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAS_CONFIG = Path(r"\\DS-KO-DO-2\docker\earnie\config\config.json")
DEFAULT_NAS_RUNTIME = Path(r"\\DS-KO-DO-2\docker\earnie\runtime")
DEFAULT_OUTPUT = ROOT / "silent-migration-test"

_SCHEMA_FILES = (
    "config.schema.json",
    "tariffs.schema.json",
    "house_profiles.schema.json",
    "backtesting_scenarios.schema.json",
    "deviation_rules.schema.json",
)

_RUNTIME_COPY_FILES = (
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


def _read_json_optional(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return _read_json(path)


def _copy_schemas(config_out: Path) -> list[str]:
    copied: list[str] = []
    repo_config = ROOT / "config"
    for name in _SCHEMA_FILES:
        src = repo_config / name
        if src.is_file():
            shutil.copy2(src, config_out / name)
            copied.append(name)
    return copied


def _copy_dotenv(config_dir: Path, config_out: Path, notes: list[str]) -> None:
    src = config_dir / ".env"
    if not src.is_file():
        notes.append(
            ".env nicht in NAS-config/ gefunden — "
            "Loxone-Zugangsdaten manuell nach silent-migration-test/config/.env legen."
        )
        return
    shutil.copy2(src, config_out / ".env")
    notes.append("config/.env von NAS lokal kopiert (Streamlit kann Credentials speichern).")


def _copy_runtime_files(nas_runtime: Path, runtime_out: Path, notes: list[str]) -> None:
    if not nas_runtime.is_dir():
        notes.append(
            f"NAS runtime nicht lesbar ({nas_runtime}) — "
            "Runtime-Dateien manuell kopieren oder `python -m scripts.bootstrap_runtime` mit "
            "EARNIE_RUNTIME_DIR=silent-migration-test/runtime ausführen."
        )
        return
    copied: list[str] = []
    for name in _RUNTIME_COPY_FILES:
        src = nas_runtime / name
        if src.is_file():
            shutil.copy2(src, runtime_out / name)
            copied.append(name)
    if copied:
        notes.append(f"Runtime von NAS kopiert: {', '.join(copied)}")
    else:
        notes.append(
            "Keine Runtime-Dateien von NAS kopiert — cons_data/state ggf. manuell bereitstellen."
        )


def _write_review(
    config_out: Path,
    output_dir: Path,
    *,
    p5_notes: list[str],
    p6_notes: list[str],
    copy_notes: list[str],
    live_settings: dict,
    nas_config: Path,
) -> None:
    lines = [
        "# Migration Review — Silent Local Test Stack",
        "",
        f"Quelle config: `{nas_config}`",
        "",
        "Alle Pfade für Worker/UI sind **lokal** unter `silent-migration-test/` "
        "(kein Schreibzugriff auf NAS nötig).",
        "",
        "## 1.26.0 P5 — Entity migration",
        "",
    ]
    if p5_notes:
        lines.extend(f"- {note}" for note in p5_notes)
    else:
        lines.append("- Keine automatischen Hinweise.")
    lines.extend(
        [
            "",
            "## 2.0 P6 — Live scenario cutover",
            "",
        ]
    )
    if p6_notes:
        lines.extend(f"- {note}" for note in p6_notes)
    else:
        lines.append("- Keine automatischen Hinweise.")
    if copy_notes:
        lines.extend(["", "## Lokale Kopien (NAS → silent-migration-test)", ""])
        lines.extend(f"- {note}" for note in copy_notes)
    lines.extend(
        [
            "",
            "## Live-Szenario (Entitäts-Referenzen)",
            "",
        ]
    )
    for key, value in sorted(live_settings.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Entfernte Legacy-Blöcke",
            "",
            "- `runtime_settings` (→ backtesting_scenarios.json)",
            "- global `awattar` (→ tariffs.json)",
            "- global `battery_wear` (→ batteries[])",
            "",
            "## Lokaler Silent-Test",
            "",
            "Prod-Worker auf der NAS **kann laufen** — dieser Stack nutzt lokales runtime/.",
            "VS Code: **main.py (Silent Migration Test)** oder:",
            "",
            "```powershell",
            f"$root = \"{ROOT}\"",
            '$env:EARNIE_CONFIG_PATH = "$root\\silent-migration-test\\config\\config.json"',
            '$env:EARNIE_RUNTIME_DIR = "$root\\silent-migration-test\\runtime"',
            '$env:EARNIE_DOTENV_PATH = "$root\\silent-migration-test\\config\\.env"',
            '$env:EARNIE_LOCAL_SETTINGS_PATH = "$root\\silent-migration-test\\runtime\\local_settings.json"',
            '$env:EARNIE_HOUSE_PROFILES_PATH = "$root\\silent-migration-test\\config\\house_profiles.json"',
            '$env:EARNIE_TARIFFS_PATH = "$root\\silent-migration-test\\config\\tariffs.json"',
            '$env:EARNIE_BACKTESTING_SCENARIOS_PATH = "$root\\silent-migration-test\\config\\backtesting_scenarios.json"',
            ".venv\\Scripts\\python.exe -m scripts.validate_tariffs --check-catalog",
            ".venv\\Scripts\\python.exe -m scripts.startup_checks",
            ".venv\\Scripts\\python.exe main.py",
            "```",
            "",
            "Erwartung: Log „Loxone Silent-Modus aktiv“; keine Loxone-Schreibbefehle.",
            "",
        ]
    )
    (config_out / "MIGRATION_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")


def setup_silent_migration_test(
    *,
    nas_config: Path,
    output_dir: Path,
    nas_runtime: Path | None = None,
    live_scenario_id: str = "live",
    force: bool = False,
) -> tuple[Path, Path]:
    """Führt P5+P6-Migration aus und schreibt silent-migration-test/ (vollständig lokal)."""
    nas_config = nas_config.resolve()
    config_dir = nas_config.parent
    runtime_src = (nas_runtime or DEFAULT_NAS_RUNTIME).resolve()
    output_dir = output_dir.resolve()
    config_out = output_dir / "config"
    runtime_out = output_dir / "runtime"

    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise FileExistsError(
            f"{output_dir} ist nicht leer — --force verwenden oder anderen Ordner wählen."
        )

    if not nas_config.is_file():
        raise FileNotFoundError(f"NAS config.json nicht gefunden: {nas_config}")

    config = _read_json(nas_config)
    tariffs_path = config_dir / "tariffs.json"
    profiles_path = config_dir / "house_profiles.json"
    if not tariffs_path.is_file():
        tariffs_path = ROOT / "config" / "tariffs.json"
    if not profiles_path.is_file():
        profiles_path = ROOT / "config" / "house_profiles.json"

    tariffs = _read_json(tariffs_path)
    profiles = _read_json(profiles_path)
    scenarios_template = _read_json_optional(config_dir / "backtesting_scenarios.json")

    p5_config, p5_tariffs, p5_profiles, p5_notes = migrate_runtime_entities(
        config,
        tariffs_doc=tariffs,
        house_profiles_doc=profiles,
    )
    p6_config, scenarios_doc, p6_notes = finalize_migration_for_2_0(
        p5_config,
        scenarios_template=scenarios_template,
        live_scenario_id=live_scenario_id,
    )

    runtime_settings_before = p5_config.get("runtime_settings", {})
    live_settings = {
        key: runtime_settings_before[key]
        for key in runtime_settings_before
        if str(runtime_settings_before.get(key, "")).strip()
    }

    config_out.mkdir(parents=True, exist_ok=True)
    runtime_out.mkdir(parents=True, exist_ok=True)

    (config_out / "config.json").write_text(
        json.dumps(p6_config, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (config_out / "tariffs.json").write_text(
        json.dumps(p5_tariffs, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (config_out / "house_profiles.json").write_text(
        json.dumps(p5_profiles, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (config_out / "backtesting_scenarios.json").write_text(
        json.dumps(scenarios_doc, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    deviation_src = config_dir / "deviation_rules.json"
    if not deviation_src.is_file():
        deviation_src = ROOT / "config" / "deviation_rules.json"
    if deviation_src.is_file():
        shutil.copy2(deviation_src, config_out / "deviation_rules.json")

    _copy_schemas(config_out)

    copy_notes: list[str] = []
    _copy_dotenv(config_dir, config_out, copy_notes)
    _copy_runtime_files(runtime_src, runtime_out, copy_notes)

    _write_review(
        config_out,
        output_dir,
        p5_notes=p5_notes,
        p6_notes=p6_notes,
        copy_notes=copy_notes,
        live_settings=live_settings,
        nas_config=nas_config,
    )

    local_settings = runtime_out / "local_settings.json"
    local_settings.write_text(
        json.dumps({"loxone_silent_mode": True}, indent=4) + "\n",
        encoding="utf-8",
    )

    return config_out, runtime_out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description=(
            "Silent-Migration-Test-Stack aus NAS-Config (P5+P6) — "
            "migrierte Config + .env + runtime lokal kopieren."
        )
    )
    parser.add_argument(
        "--nas-config",
        type=Path,
        default=DEFAULT_NAS_CONFIG,
        help=f"Quell-config.json (Standard: {DEFAULT_NAS_CONFIG})",
    )
    parser.add_argument(
        "--nas-runtime",
        type=Path,
        default=DEFAULT_NAS_RUNTIME,
        help=f"Quell-runtime/ zum Kopieren (Standard: {DEFAULT_NAS_RUNTIME})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Zielordner (Standard: {DEFAULT_OUTPUT.name}/)",
    )
    parser.add_argument(
        "--live-scenario-id",
        default="live",
        help="ID des Live-Szenarios in backtesting_scenarios.json (Standard: live)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bestehenden output-dir überschreiben",
    )
    args = parser.parse_args(argv)

    try:
        config_out, runtime_out = setup_silent_migration_test(
            nas_config=args.nas_config,
            output_dir=args.output_dir,
            nas_runtime=args.nas_runtime,
            live_scenario_id=args.live_scenario_id,
            force=args.force,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(f"Silent-Migration-Test-Stack geschrieben nach: {args.output_dir.resolve()}")
    print(f"  config/: {config_out} (inkl. .env-Kopie)")
    print(f"  runtime/: {runtime_out} (NAS-runtime-Kopie + local_settings.json)")
    print(f"  Review: {config_out / 'MIGRATION_REVIEW.md'}")
    print()
    print("Nächste Schritte:")
    print("  1. MIGRATION_REVIEW.md lesen und Entitäts-IDs prüfen")
    print("  2. VS Code: main.py (Silent Migration Test) — alles lokal, kein NAS-Schreibzugriff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
