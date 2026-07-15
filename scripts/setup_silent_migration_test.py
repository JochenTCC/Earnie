#!/usr/bin/env python3
"""Erzeugt silent-migration-test/ mit vollständiger P5+P6-Migration aus NAS-Config."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path

from house_config.migrate_runtime_entities import (
    RUNTIME_ID_KEYS,
    RUNTIME_STRIP_KEYS,
    finalize_migration_for_2_0,
    migrate_runtime_entities,
    _split_components_from_config,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAS_CONFIG = Path(r"\\DS-KO-DO-2\docker\earnie\config\config.json")
DEFAULT_NAS_RUNTIME = Path(r"\\DS-KO-DO-2\docker\earnie\runtime")
DEFAULT_OUTPUT = ROOT / "silent-migration-test"

_SCHEMA_FILES = (
    "config.schema.json",
    "components.schema.json",
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
    try:
        shutil.copy2(src, config_out / ".env")
    except OSError as exc:
        notes.append(
            f".env von NAS nicht lesbar ({exc}) — "
            "Loxone-Zugangsdaten manuell nach silent-migration-test/config/.env legen."
        )
        return
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


_LEGACY_FLEX_IDS = frozenset({"eauto", "swimspa", "swimspa_filter", "waermepumpe"})


def _apply_flex_consumer_migration(
    config_dir: Path,
    *,
    profile_id: str,
) -> list[dict]:
    """1.95c: legacy flexible_consumers[] → house_profiles.json (idempotent)."""
    from scripts.migrate_flex_consumers import migrate_prod_consumers

    config_path = config_dir / "config.json"
    profiles_path = config_dir / "house_profiles.json"
    config = _read_json(config_path)
    flex_ids = {
        str(entry.get("id", ""))
        for entry in config.get("flexible_consumers", [])
        if isinstance(entry, dict)
    }
    if not flex_ids & _LEGACY_FLEX_IDS:
        return []
    profiles_doc = _read_json(profiles_path)
    config_out, profiles_out, status = migrate_prod_consumers(
        config,
        profiles_doc,
        profile_id=profile_id,
    )
    config_path.write_text(
        json.dumps(config_out, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    profiles_path.write_text(
        json.dumps(profiles_out, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return status


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


def _resolve_tariffs_for_silent_test(tariffs_path: Path) -> tuple[dict, list[str]]:
    """Prod-NAS liefert oft nur ein Tarif-Subset — für Tests den Repo-Katalog nutzen."""
    notes: list[str] = []
    repo_tariffs = ROOT / "config" / "tariffs.json"
    if tariffs_path.is_file():
        nas_doc = _read_json(tariffs_path)
    else:
        nas_doc = {"import_tariffs": [], "export_tariffs": []}
    nas_import = len(nas_doc.get("import_tariffs", []))
    nas_export = len(nas_doc.get("export_tariffs", []))
    if repo_tariffs.is_file() and (nas_import < 10 or nas_export < 8):
        notes.append(
            f"tariffs.json aus Repo-Katalog übernommen "
            f"(NAS-Subset: {nas_import} Import, {nas_export} Export)."
        )
        return _read_json(repo_tariffs), notes
    notes.append("tariffs.json von NAS übernommen.")
    return nas_doc, notes


def _find_live_scenario_settings(scenarios_doc: dict, live_id: str) -> dict:
    scenarios = scenarios_doc.get("scenarios", [])
    if not isinstance(scenarios, list):
        return {}
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() != live_id:
            continue
        settings = item.get("settings", {})
        if isinstance(settings, dict):
            return settings
    return {}


def _nas_already_migrated(config: dict) -> bool:
    """True wenn NAS bereits live_scenario_id hat (2.0) oder nur ID-runtime_settings."""
    if str(config.get("live_scenario_id", "")).strip():
        return True
    runtime = config.get("runtime_settings")
    if not isinstance(runtime, dict):
        return False
    flat_remaining = [key for key in RUNTIME_STRIP_KEYS if key in runtime]
    if flat_remaining:
        return False
    return any(str(runtime.get(key, "")).strip() for key in RUNTIME_ID_KEYS)


def _sync_from_migrated_nas(
    *,
    config: dict,
    tariffs: dict,
    profiles: dict,
    scenarios_doc: dict | None,
    live_scenario_id: str,
) -> tuple[dict, dict, dict, dict, dict, list[str], list[str]]:
    """Kopiert bereits migrierte NAS-Config (2.0) und splittet components.json."""
    p5_notes = ["NAS bereits 2.0 — Sidecars direkt übernommen (kein P5-Lauf)."]
    p6_notes: list[str] = []
    live_id = str(config.get("live_scenario_id") or live_scenario_id).strip() or "live"
    scenarios_out = copy.deepcopy(scenarios_doc or {"scenarios": []})
    live_settings = _find_live_scenario_settings(scenarios_out, live_id)
    if not live_settings:
        raise ValueError(
            f"Live-Szenario '{live_id}' nicht in backtesting_scenarios.json gefunden."
        )
    config_out, components_doc = _split_components_from_config(config)
    if config.get("batteries") or config.get("pv_systems"):
        p6_notes.append(
            "batteries[] / pv_systems[] nach components.json verschoben (2.0 Components)."
        )
    else:
        p6_notes.append("components.json aus NAS-config erzeugt.")
    p6_notes.append(f"Live-Szenario '{live_id}' aus backtesting_scenarios.json übernommen.")
    return config_out, tariffs, profiles, scenarios_out, components_doc, p5_notes, p6_notes


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

    tariffs, tariff_notes = _resolve_tariffs_for_silent_test(tariffs_path)
    profiles = _read_json(profiles_path)
    scenarios_template = _read_json_optional(config_dir / "backtesting_scenarios.json")

    if _nas_already_migrated(config):
        (
            p6_config,
            p5_tariffs,
            p5_profiles,
            scenarios_doc,
            components_doc,
            p5_notes,
            p6_notes,
        ) = _sync_from_migrated_nas(
            config=config,
            tariffs=tariffs,
            profiles=profiles,
            scenarios_doc=scenarios_template,
            live_scenario_id=live_scenario_id,
        )
        live_settings = _find_live_scenario_settings(
            scenarios_doc,
            str(p6_config.get("live_scenario_id") or live_scenario_id).strip() or "live",
        )
    else:
        p5_config, p5_tariffs, p5_profiles, p5_notes = migrate_runtime_entities(
            config,
            tariffs_doc=tariffs,
            house_profiles_doc=profiles,
        )
        p6_config, scenarios_doc, components_doc, p6_notes = finalize_migration_for_2_0(
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
    (config_out / "components.json").write_text(
        json.dumps(components_doc, indent=4, ensure_ascii=False) + "\n",
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

    profile_id = str(live_settings.get("house_profile_id") or "example_efh").strip() or "example_efh"
    flex_status = _apply_flex_consumer_migration(config_out, profile_id=profile_id)
    if flex_status:
        p6_notes.append(
            f"migrate_flex_consumers: {len(flex_status)} Verbraucher-Zeilen "
            f"nach Profil '{profile_id}' migriert."
        )

    copy_notes: list[str] = list(tariff_notes)
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
        json.dumps(
            {"loxone_silent_mode": True, "chart_debug_capture_enabled": True},
            indent=4,
        )
        + "\n",
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
