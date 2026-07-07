#!/usr/bin/env python3
"""Archiviert einen Produktiv-Dump als versionierte Regression-Fixture."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from runtime_store.debug_dump_inputs import collect_dump_context, copy_inputs_to_directory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "runtime-prod"
FIXTURES_ROOT = ROOT / "tests" / "fixtures" / "prod_dumps"

ARCHIVE_FILES = (
    "optimization_history.jsonl",
    "flexible_consumers_state.json",
    "optimizer_run_state.json",
    "live_optimization_debug.json",
    "pv_counter_state.json",
)


def _dir_with_history(path: Path) -> Path | None:
    if (path / "optimization_history.jsonl").is_file():
        return path
    return None


def _resolve_source_dir(source: Path) -> Path:
    if source.is_dir():
        for candidate in (
            source,
            source / "runtime",
            source / "data",
            source / "_full",
        ):
            found = _dir_with_history(candidate)
            if found is not None:
                return found
        raise FileNotFoundError(
            f"Kein optimization_history.jsonl unter {source} "
            "(erwartet Ordner, runtime/, data/, _full/ oder .zip)"
        )
    if source.is_file() and source.suffix.lower() == ".zip":
        target = source.parent / "_archive_extract"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        with zipfile.ZipFile(source, "r") as archive:
            archive.extractall(target)
        for candidate in (
            target,
            target / "runtime",
            target / "data",
        ):
            found = _dir_with_history(candidate)
            if found is not None:
                return found
        raise FileNotFoundError(
            f"Kein optimization_history.jsonl in {source} "
            "(ZIP mit runtime/ oder flachem Ordner erwartet)"
        )
    raise FileNotFoundError(f"Quelle nicht gefunden: {source}")


def _write_manifest(
    target: Path,
    *,
    case_id: str,
    title: str,
    symptom: str,
    app_version: str,
    recorded_at: str,
    files: list[str],
    regression: dict,
    env_overrides: dict[str, str],
    resolved_paths: dict[str, str],
) -> None:
    manifest = {
        "id": case_id,
        "title": title,
        "symptom": symptom,
        "recorded_at": recorded_at,
        "app_version": app_version,
        "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "env_overrides": env_overrides,
        "resolved_paths": resolved_paths,
        "regression": regression,
    }
    with open(target / "manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def archive_prod_dump(
    *,
    case_id: str,
    title: str,
    symptom: str,
    source: Path,
    app_version: str,
    recorded_at: str,
    regression: dict | None,
    force: bool,
) -> Path:
    if not case_id or any(ch in case_id for ch in r"\/:*?<>|"):
        raise ValueError(f"Ungültige Fall-ID: {case_id!r}")

    target = FIXTURES_ROOT / case_id
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} existiert bereits – --force zum Überschreiben"
        )
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    source_dir = _resolve_source_dir(source)
    copied: list[str] = []
    for name in ARCHIVE_FILES:
        src = source_dir / name
        if not src.is_file():
            continue
        shutil.copy2(src, target / name)
        copied.append(name)
    copied.extend(copy_inputs_to_directory(target))

    if "optimization_history.jsonl" not in copied:
        raise FileNotFoundError(
            f"optimization_history.jsonl fehlt in {source_dir} – Archiv abgebrochen"
        )

    dump_context = collect_dump_context()

    _write_manifest(
        target,
        case_id=case_id,
        title=title,
        symptom=symptom,
        app_version=app_version,
        recorded_at=recorded_at,
        files=copied,
        env_overrides=dump_context["env_overrides"],
        resolved_paths=dump_context["resolved_paths"],
        regression=regression or {},
    )
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Produktiv-Dump nach tests/fixtures/prod_dumps/ archivieren",
    )
    parser.add_argument("--id", required=True, help="Eindeutige Fall-Kennung (Ordnername)")
    parser.add_argument("--title", required=True, help="Kurzbeschreibung")
    parser.add_argument("--symptom", required=True, help="Beobachtetes Fehlerbild")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE / "runtime.zip",
        help="Ordner oder ZIP (Standard: runtime-prod/runtime.zip)",
    )
    parser.add_argument("--app-version", default="", help="App-Version aus dem Dump")
    parser.add_argument(
        "--recorded-at",
        default=datetime.now().date().isoformat(),
        help="Datum des Vorfalls (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--regression-json",
        default="",
        help="JSON-Objekt mit Regression-Metriken (optional)",
    )
    parser.add_argument("--force", action="store_true", help="Bestehendes Archiv überschreiben")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    regression = {}
    if args.regression_json.strip():
        regression = json.loads(args.regression_json)
    target = archive_prod_dump(
        case_id=args.id,
        title=args.title,
        symptom=args.symptom,
        source=args.source,
        app_version=args.app_version,
        recorded_at=args.recorded_at,
        regression=regression,
        force=args.force,
    )
    print(f"Archiv angelegt: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
