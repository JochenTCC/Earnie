"""Laden und Validieren von config/tariffs.json."""
from __future__ import annotations

import json
import os

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates

IMPORT_TYPES = frozenset({"awattar", "fixed_cent"})
EXPORT_TYPES = frozenset({"fixed", "monthly_table", "dynamic_epex"})


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {"import_tariffs": [], "export_tariffs": []}
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return json.load(handle)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"tariffs.json '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def _normalize_import_tariff(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"import_tariffs[{index}] muss ein Objekt sein.")
    tariff_id = str(raw.get("id", "")).strip()
    if not tariff_id:
        raise ValueError(f"import_tariffs[{index}]: id fehlt.")
    tariff_type = str(raw.get("type", "")).strip().lower()
    if tariff_type not in IMPORT_TYPES:
        raise ValueError(
            f"import_tariffs[{index}] ('{tariff_id}'): type muss awattar oder fixed_cent sein."
        )
    label = str(raw.get("label", tariff_id)).strip() or tariff_id
    spec: dict = {"id": tariff_id, "label": label, "type": tariff_type}
    if tariff_type == "fixed_cent":
        if "fix_cent_kwh" not in raw:
            raise ValueError(
                f"import_tariffs[{index}] ('{tariff_id}'): fix_cent_kwh fehlt."
            )
        spec["fix_cent_kwh"] = float(raw["fix_cent_kwh"])
    return spec


def _normalize_export_tariff(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"export_tariffs[{index}] muss ein Objekt sein.")
    tariff_id = str(raw.get("id", "")).strip()
    if not tariff_id:
        raise ValueError(f"export_tariffs[{index}]: id fehlt.")
    tariff_type = str(raw.get("type", "")).strip().lower()
    if tariff_type not in EXPORT_TYPES:
        raise ValueError(
            f"export_tariffs[{index}] ('{tariff_id}'): "
            "type muss fixed, monthly_table oder dynamic_epex sein."
        )
    label = str(raw.get("label", tariff_id)).strip() or tariff_id
    spec: dict = {"id": tariff_id, "label": label, "type": tariff_type}
    if tariff_type == "fixed":
        if "k_push_cent" not in raw:
            raise ValueError(
                f"export_tariffs[{index}] ('{tariff_id}'): k_push_cent fehlt."
            )
        spec["k_push_cent"] = float(raw["k_push_cent"])
    elif tariff_type == "monthly_table":
        rates = raw.get("monthly_rates")
        if not isinstance(rates, list):
            raise ValueError(
                f"export_tariffs[{index}] ('{tariff_id}'): monthly_rates fehlt."
            )
        spec["monthly_rates"] = validate_fixed_monthly_feed_in_rates(rates)
    return spec


def normalize_tariffs_document(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("tariffs.json muss ein Objekt sein.")
    imports_raw = doc.get("import_tariffs", [])
    exports_raw = doc.get("export_tariffs", [])
    if not isinstance(imports_raw, list):
        raise ValueError("import_tariffs muss ein Array sein.")
    if not isinstance(exports_raw, list):
        raise ValueError("export_tariffs muss ein Array sein.")
    imports: dict[str, dict] = {}
    for index, item in enumerate(imports_raw):
        spec = _normalize_import_tariff(item, index)
        if spec["id"] in imports:
            raise ValueError(f"import_tariffs: doppelte id '{spec['id']}'.")
        imports[spec["id"]] = spec
    exports: dict[str, dict] = {}
    for index, item in enumerate(exports_raw):
        spec = _normalize_export_tariff(item, index)
        if spec["id"] in exports:
            raise ValueError(f"export_tariffs: doppelte id '{spec['id']}'.")
        exports[spec["id"]] = spec
    return {"import_tariffs": imports, "export_tariffs": exports}


def load_tariffs_document(path: str) -> dict:
    return normalize_tariffs_document(_read_json(path))


def resolve_import_tariff_into_settings(settings: dict, tariffs: dict) -> dict:
    out = dict(settings)
    tariff_id = out.pop("import_tariff_id", None)
    if not tariff_id:
        return out
    tariff_id = str(tariff_id).strip()
    import_map = tariffs.get("import_tariffs", {})
    if tariff_id not in import_map:
        raise ValueError(f"Unbekannte import_tariff_id '{tariff_id}'.")
    tariff = import_map[tariff_id]
    if tariff["type"] == "fixed_cent":
        out["import_fixed_cent_kwh"] = tariff["fix_cent_kwh"]
    out["import_tariff_type"] = tariff["type"]
    return out


def resolve_export_tariff_into_settings(
    settings: dict,
    tariffs: dict,
    *,
    monthly_rates_holder: dict | None = None,
) -> dict:
    """Setzt feed_in_mode/k_push_cent; monthly_table → holder['_monthly_fixed_tariffs']."""
    out = dict(settings)
    tariff_id = out.pop("export_tariff_id", None)
    if not tariff_id:
        return out
    tariff_id = str(tariff_id).strip()
    export_map = tariffs.get("export_tariffs", {})
    if tariff_id not in export_map:
        raise ValueError(f"Unbekannte export_tariff_id '{tariff_id}'.")
    tariff = export_map[tariff_id]
    if tariff["type"] == "fixed":
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = tariff["k_push_cent"]
    elif tariff["type"] == "dynamic_epex":
        out["feed_in_mode"] = "dynamic_epex"
    elif tariff["type"] == "monthly_table":
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = float(out.get("k_push_cent", 0.0) or 0.0)
        if monthly_rates_holder is not None:
            monthly_rates_holder["_monthly_fixed_tariffs"] = tariff["monthly_rates"]
    return out
