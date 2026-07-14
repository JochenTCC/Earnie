#!/usr/bin/env python3
"""CLI: Tarifkatalog-Plausibilität (Deploy-Gate, CI, manuelle Prüfung)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from house_config.tariff_plausibility import (
    collect_tariff_plausibility_errors,
    format_tariff_plausibility_errors,
)
from house_config.tariffs_store import load_tariffs_document
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_tariffs_json_path,
    resolve_tariffs_schema_template_path,
)


def _check_dach_source_coverage(
    *,
    tariffs_path: str,
    import_json: str,
    export_json: str,
) -> list[str]:
    from tools.convert_dach_tariffs import convert_document

    converted = convert_document(Path(import_json), Path(export_json))
    current = load_tariffs_document(tariffs_path)
    errors: list[str] = []

    conv_import = {item["id"] for item in converted["import_tariffs"]}
    cur_import = set(current.get("import_tariffs", {}))
    missing_import = sorted(conv_import - cur_import)
    if missing_import:
        errors.append(
            "Import-Tarife aus Quelle fehlen im Katalog: "
            + ", ".join(missing_import)
        )

    conv_export = {item["id"] for item in converted["export_tariffs"]}
    cur_export = set(current.get("export_tariffs", {}))
    missing_export = sorted(conv_export - cur_export)
    if missing_export:
        errors.append(
            "Export-Tarife aus Quelle fehlen im Katalog: "
            + ", ".join(missing_export)
        )
    return errors


def run_validation(
    *,
    tariffs_path: str,
    scenarios_path: str | None,
    schema_path: str | None,
    check_catalog: bool,
    import_json: str,
    export_json: str,
) -> list[str]:
    errors = collect_tariff_plausibility_errors(
        tariffs_path=tariffs_path,
        scenarios_path=scenarios_path,
        schema_path=schema_path,
    )
    if check_catalog:
        errors.extend(
            _check_dach_source_coverage(
                tariffs_path=tariffs_path,
                import_json=import_json,
                export_json=export_json,
            )
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prüft config/tariffs.json (Plausibilität, optional DACH-Vollständigkeit)."
    )
    parser.add_argument(
        "--tariffs",
        default=None,
        help="Pfad zu tariffs.json (Standard: neben config.json)",
    )
    parser.add_argument(
        "--scenarios",
        default=None,
        help="Pfad zu backtesting_scenarios.json (Standard: neben config.json)",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Pfad zu tariffs.schema.json (Standard: Bundled-Vorlage)",
    )
    parser.add_argument(
        "--skip-scenarios",
        action="store_true",
        help="Szenario-Referenzen nicht prüfen",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="JSON-Schema-Prüfung überspringen",
    )
    parser.add_argument(
        "--check-catalog",
        action="store_true",
        help="Vollständigkeit gegen stromtarife/einspeisetarife DACH-JSONs prüfen",
    )
    parser.add_argument(
        "--import-json",
        default="stromtarife_dach_kombiniert.json",
        help="Bezugstarife-Quelle für --check-catalog",
    )
    parser.add_argument(
        "--export-json",
        default="einspeisetarife_dach_erweitert.json",
        help="Einspeisetarife-Quelle für --check-catalog",
    )
    args = parser.parse_args(argv)

    tariffs_path = args.tariffs or resolve_tariffs_json_path()
    scenarios_path = None if args.skip_scenarios else (
        args.scenarios or resolve_backtesting_scenarios_json_path()
    )
    schema_path = None if args.skip_schema else (
        args.schema or resolve_tariffs_schema_template_path()
    )

    errors = run_validation(
        tariffs_path=tariffs_path,
        scenarios_path=scenarios_path,
        schema_path=schema_path,
        check_catalog=args.check_catalog,
        import_json=args.import_json,
        export_json=args.export_json,
    )
    if errors:
        print(format_tariff_plausibility_errors(errors), file=sys.stderr)
        return 1

    print(f"OK: {tariffs_path}")
    if args.check_catalog:
        print(
            f"  DACH-Quellen abgedeckt ({args.import_json}, {args.export_json})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
