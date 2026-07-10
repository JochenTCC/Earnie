"""Laden und Validieren von config/tariffs.json."""
from __future__ import annotations

import json
import os
import re

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates
from data.tariff_pricing import market_zone_for_land

IMPORT_TYPES = frozenset(
    {"awattar", "fixed_cent", "spot_hourly", "ex_post_spot", "monthly_market"}
)
EXPORT_TYPES = frozenset(
    {
        "fixed",
        "monthly_table",
        "monthly_float",
        "dynamic_epex",
        "spot_hourly",
        "ex_post_spot",
    }
)
VALID_LANDS = frozenset({"AT", "DE", "CH"})
VALID_CURRENCIES = frozenset({"EUR", "CHF"})
# Umbenannte IDs aus Tarifkatalog 1.24.f (Abwärtskompatibilität für runtime_settings).
_EXPORT_TARIFF_ID_ALIASES: dict[str, str] = {
    "awattar_sunny_float": "dynamic_epex",
}


def resolve_export_tariff_id(tariff_id: str) -> str:
    """Mappt veraltete export_tariff_id auf den aktuellen Katalog-Eintrag."""
    key = str(tariff_id).strip()
    return _EXPORT_TARIFF_ID_ALIASES.get(key, key)


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


def _optional_float(raw: dict, key: str) -> float | None:
    if key not in raw or raw[key] is None:
        return None
    return float(raw[key])


def _normalize_dach_fields(raw: dict, spec: dict) -> None:
    if "land" in raw and raw["land"] is not None:
        land = str(raw["land"]).strip().upper()
        if land not in VALID_LANDS:
            raise ValueError(f"land muss AT, DE oder CH sein, nicht {raw['land']!r}.")
        spec["land"] = land
    if "currency" in raw and raw["currency"] is not None:
        currency = str(raw["currency"]).strip().upper()
        if currency not in VALID_CURRENCIES:
            raise ValueError(f"currency muss EUR oder CHF sein, nicht {raw['currency']!r}.")
        spec["currency"] = currency
    for key in (
        "settlement_fee_cent_kwh",
        "markup_percent",
        "vat_percent",
        "netzentgelt_cent_kwh",
    ):
        value = _optional_float(raw, key)
        if value is not None:
            spec[key] = value
    if "prices_include_vat" in raw:
        spec["prices_include_vat"] = bool(raw["prices_include_vat"])
    notes = raw.get("notes")
    if notes is not None and str(notes).strip():
        spec["notes"] = str(notes).strip()


def _import_tariff_spec(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"import_tariffs[{index}] muss ein Objekt sein.")
    tariff_id = str(raw.get("id", "")).strip()
    if not tariff_id:
        raise ValueError(f"import_tariffs[{index}]: id fehlt.")
    tariff_type = str(raw.get("type", "")).strip().lower()
    if tariff_type not in IMPORT_TYPES:
        raise ValueError(
            f"import_tariffs[{index}] ('{tariff_id}'): unbekannter type '{tariff_type}'."
        )
    label = str(raw.get("label", tariff_id)).strip() or tariff_id
    spec: dict = {"id": tariff_id, "label": label, "type": tariff_type}
    _normalize_dach_fields(raw, spec)
    if tariff_type == "fixed_cent":
        if "fix_cent_kwh" not in raw:
            raise ValueError(
                f"import_tariffs[{index}] ('{tariff_id}'): fix_cent_kwh fehlt."
            )
        spec["fix_cent_kwh"] = float(raw["fix_cent_kwh"])
    elif tariff_type in {"spot_hourly", "ex_post_spot", "monthly_market"}:
        if "land" not in spec:
            raise ValueError(
                f"import_tariffs[{index}] ('{tariff_id}'): land fehlt für {tariff_type}."
            )
    return spec


def _export_tariff_spec(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"export_tariffs[{index}] muss ein Objekt sein.")
    tariff_id = str(raw.get("id", "")).strip()
    if not tariff_id:
        raise ValueError(f"export_tariffs[{index}]: id fehlt.")
    tariff_type = str(raw.get("type", "")).strip().lower()
    if tariff_type not in EXPORT_TYPES:
        raise ValueError(
            f"export_tariffs[{index}] ('{tariff_id}'): unbekannter type '{tariff_type}'."
        )
    label = str(raw.get("label", tariff_id)).strip() or tariff_id
    spec: dict = {"id": tariff_id, "label": label, "type": tariff_type}
    _normalize_dach_fields(raw, spec)
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
    elif tariff_type == "monthly_float":
        if "arbeitspreis_kwh_cent" not in raw:
            raise ValueError(
                f"export_tariffs[{index}] ('{tariff_id}'): arbeitspreis_kwh_cent fehlt."
            )
        spec["arbeitspreis_kwh_cent"] = float(raw["arbeitspreis_kwh_cent"])
    elif tariff_type in {"spot_hourly", "ex_post_spot"}:
        if "land" not in spec:
            raise ValueError(
                f"export_tariffs[{index}] ('{tariff_id}'): land fehlt für {tariff_type}."
            )
    return spec


def _normalize_import_tariff(raw: dict, index: int) -> dict:
    return _import_tariff_spec(raw, index)


def _normalize_export_tariff(raw: dict, index: int) -> dict:
    return _export_tariff_spec(raw, index)


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
    normalized: dict = {"import_tariffs": imports, "export_tariffs": exports}
    catalog_as_of = doc.get("catalog_as_of")
    if catalog_as_of is not None and str(catalog_as_of).strip():
        normalized["catalog_as_of"] = str(catalog_as_of).strip()
    return normalized


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
    tariff = dict(import_map[tariff_id])
    out["_import_tariff_spec"] = tariff
    out["import_tariff_type"] = tariff["type"]
    if tariff["type"] == "fixed_cent":
        out["import_fixed_cent_kwh"] = tariff["fix_cent_kwh"]
    if "land" in tariff:
        out["market_zone"] = market_zone_for_land(tariff["land"])
    if out.get("netzentgelt_cent_kwh_override") is not None:
        out["netzentgelt_cent_kwh"] = float(out.pop("netzentgelt_cent_kwh_override"))
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
    tariff_id = resolve_export_tariff_id(str(tariff_id).strip())
    export_map = tariffs.get("export_tariffs", {})
    if tariff_id not in export_map:
        raise ValueError(f"Unbekannte export_tariff_id '{tariff_id}'.")
    tariff = dict(export_map[tariff_id])
    out["_export_tariff_spec"] = tariff
    if tariff["type"] == "fixed":
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = tariff["k_push_cent"]
    elif tariff["type"] == "dynamic_epex":
        out["feed_in_mode"] = "dynamic_epex"
    elif tariff["type"] in {"spot_hourly", "ex_post_spot"}:
        out["feed_in_mode"] = "dynamic_epex"
        out["k_push_cent"] = float(out.get("k_push_cent", 0.0) or 0.0)
    elif tariff["type"] == "monthly_table":
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = float(out.get("k_push_cent", 0.0) or 0.0)
        if monthly_rates_holder is not None:
            monthly_rates_holder["_monthly_fixed_tariffs"] = tariff["monthly_rates"]
    elif tariff["type"] == "monthly_float":
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = float(out.get("k_push_cent", 0.0) or 0.0)
    return out


def slugify_tariff_id(*parts: str) -> str:
    raw = "_".join(str(part).strip().lower() for part in parts if str(part).strip())
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug[:80] or "tariff"
