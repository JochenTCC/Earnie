#!/usr/bin/env python3
"""Konvertiert DACH-Prototyp-JSONs in config/tariffs.json (Version 1.24.f P3)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from house_config.tariffs_store import slugify_tariff_id

LEGACY_IMPORT_IDS = {
    ("aWATTar", "HOURLY", "AT"): ("awattar_at", "awattar"),
}
LEGACY_EXPORT_IDS = {
    ("aWATTar", "SUNNY", "AT"): "dynamic_epex",
    ("aWATTar", "SUNNY SPOT", "AT"): "dynamic_epex",
}


def _catalog_as_of(meta: dict) -> str:
    text = str(meta.get("beschreibung", ""))
    match = re.search(r"Stand\s+(\d{4})", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown"


def _import_type(entry: dict) -> str:
    legacy = LEGACY_IMPORT_IDS.get(
        (entry["stromlieferant"], entry["tarifname"], entry["land"])
    )
    if legacy:
        return legacy[1]
    if entry["tarif_typ"] == "fix":
        return "fixed_cent"
    hint = str(entry.get("hinweis", "")).lower()
    if "ex-post" in hint or "ex post" in hint:
        return "ex_post_spot"
    if "marktwert" in hint or "monatlich" in hint:
        return "monthly_market"
    return "spot_hourly"


def _export_type(entry: dict) -> str:
    legacy = LEGACY_EXPORT_IDS.get(
        (entry["stromlieferant"], entry["tarifname"], entry["land"])
    )
    if legacy:
        return legacy
    if entry["tarif_typ"] == "monthly_float":
        return "monthly_float"
    if entry["tarif_typ"] == "fix":
        return "fixed"
    hint = str(entry.get("hinweis", "")).lower()
    if "ex-post" in hint or "ex post" in hint:
        return "ex_post_spot"
    return "spot_hourly"


def _tariff_id(entry: dict, *, export: bool) -> str:
    legacy_import = LEGACY_IMPORT_IDS.get(
        (entry["stromlieferant"], entry["tarifname"], entry["land"])
    )
    if legacy_import:
        return legacy_import[0]
    if export:
        legacy_export = LEGACY_EXPORT_IDS.get(
            (entry["stromlieferant"], entry["tarifname"], entry["land"])
        )
        if legacy_export == "dynamic_epex":
            return "dynamic_epex"
    return slugify_tariff_id(
        entry["land"],
        entry["stromlieferant"],
        entry["tarifname"],
    )


def _common_fields(entry: dict) -> dict:
    fields: dict = {
        "land": entry["land"],
        "currency": entry["waehrung"],
        "settlement_fee_cent_kwh": float(entry.get("abwicklungsgebuehr_kwh_cent") or 0.0),
        "markup_percent": float(entry.get("aufschlag_prozent") or 0.0),
        "prices_include_vat": bool(entry.get("preise_inkl_ust", True)),
        "vat_percent": float(entry.get("mwst_prozent") or 0.0),
    }
    hint = entry.get("hinweis")
    if hint:
        fields["notes"] = str(hint)
    return fields


def convert_import(entry: dict) -> dict:
    tariff_type = _import_type(entry)
    item: dict = {
        "id": _tariff_id(entry, export=False),
        "label": f"{entry['stromlieferant']} — {entry['tarifname']}",
        "type": tariff_type,
        **_common_fields(entry),
    }
    if tariff_type == "fixed_cent":
        item["fix_cent_kwh"] = float(entry["arbeitspreis_kwh_cent"])
    return item


def convert_export(entry: dict) -> dict:
    tariff_type = _export_type(entry)
    item: dict = {
        "id": _tariff_id(entry, export=True),
        "label": f"{entry['stromlieferant']} — {entry['tarifname']}",
        "type": tariff_type,
        **_common_fields(entry),
    }
    if tariff_type == "fixed":
        item["k_push_cent"] = float(entry["arbeitspreis_kwh_cent"])
    elif tariff_type == "monthly_float":
        item["arbeitspreis_kwh_cent"] = float(entry["arbeitspreis_kwh_cent"])
    return item


def convert_document(
    import_path: Path,
    export_path: Path,
) -> dict:
    import_doc = json.loads(import_path.read_text(encoding="utf-8"))
    export_doc = json.loads(export_path.read_text(encoding="utf-8"))
    catalog_as_of = _catalog_as_of(import_doc.get("meta", {}))
    imports = [convert_import(entry) for entry in import_doc["tarife"]]
    exports = [convert_export(entry) for entry in export_doc["tarife"]]
    return {
        "$schema": "./tariffs.schema.json",
        "catalog_as_of": catalog_as_of,
        "import_tariffs": imports,
        "export_tariffs": exports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DACH-Tarifkatalog nach tariffs.json konvertieren.")
    parser.add_argument(
        "--import-json",
        default="stromtarife_dach_kombiniert.json",
        help="Bezugstarife (DACH-Prototyp)",
    )
    parser.add_argument(
        "--export-json",
        default="einspeisetarife_dach_erweitert.json",
        help="Einspeisetarife (DACH-Prototyp, erweitert)",
    )
    parser.add_argument(
        "--output",
        default="config/tariffs.json",
        help="Ziel tariffs.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Nur prüfen: alle DACH-Quell-Einträge im Ziel-Katalog? (Exit 1 bei Lücken)",
    )
    args = parser.parse_args()
    if args.check:
        from scripts.validate_tariffs import run_validation

        errors = run_validation(
            tariffs_path=args.output,
            scenarios_path=None,
            schema_path=None,
            check_catalog=True,
            import_json=args.import_json,
            export_json=args.export_json,
        )
        if errors:
            for item in errors:
                print(item, file=sys.stderr)
            raise SystemExit(1)
        print(f"OK: {args.output} deckt DACH-Quellen ab.")
        return

    doc = convert_document(Path(args.import_json), Path(args.export_json))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(doc, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(
        f"Geschrieben: {output} "
        f"({len(doc['import_tariffs'])} Import, {len(doc['export_tariffs'])} Export, "
        f"catalog_as_of={doc['catalog_as_of']})"
    )


if __name__ == "__main__":
    main()
