"""Laden und Validieren von config/tariffs.json."""
from __future__ import annotations

import json
import os
import re

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates
from data.tariff_pricing import market_zone_for_land

IMPORT_TYPES = frozenset(
    {
        "fixed_cent",
        "spot_hourly",
        "ex_post_spot",
        "monthly_market",
        "monthly_table",
    }
)
EXPORT_TYPES = frozenset(
    {
        "fixed",
        "monthly_table",
        "spot_hourly",
        "ex_post_spot",
    }
)
VALID_LANDS = frozenset({"AT", "DE", "CH"})
VALID_CURRENCIES = frozenset({"EUR", "CHF"})
# Umbenannte IDs aus Tarifkatalog 1.24.f (reject set for soft-alias).
_EXPORT_TARIFF_ID_ALIASES: dict[str, str] = {
    "awattar_sunny_float": "dynamic_epex",
}
# Pre-spot_hourly type names (reject → spot_hourly).
_LEGACY_IMPORT_TYPES: dict[str, str] = {
    "awattar": "spot_hourly",
}
_LEGACY_EXPORT_TYPES: dict[str, str] = {
    "dynamic_epex": "spot_hourly",
}
# Legacy tariff ids that must share one supplier_id for monthly-fee dedupe.
_SUPPLIER_ID_BY_TARIFF_ID: dict[str, str] = {
    "awattar_at": "awattar_at",
    "dynamic_epex": "awattar_at",
    "monthly_sunny": "awattar_at",
    "monthly_sunny_web_recherche": "awattar_at",
    "de_awattar_de_hourly_de": "awattar_de",
}
_SPOT_EXPORT_FEE_KEYS = (
    "feed_in_fee_factor",
    "feed_in_fix_cent",
)


def resolve_export_tariff_id(tariff_id: str) -> str:
    """Reject renamed export tariff ids; return unchanged when current."""
    key = str(tariff_id).strip()
    replacement = _EXPORT_TARIFF_ID_ALIASES.get(key)
    if replacement is not None:
        raise ValueError(
            f"Veraltete export_tariff_id '{key}' — bitte '{replacement}' verwenden."
        )
    return key


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


def slugify_tariff_id(*parts: str) -> str:
    raw = "_".join(str(part).strip().lower() for part in parts if str(part).strip())
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug[:80] or "tariff"


def _supplier_id_from_label(label: str) -> str:
    text = str(label or "").strip()
    for sep in (" — ", " – ", " - "):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    return slugify_tariff_id(text)


def resolve_supplier_id(
    raw: dict,
    *,
    tariff_id: str,
    label: str,
) -> str:
    """Required supplier slug; soft-fills from legacy map / label when missing."""
    explicit = str(raw.get("supplier_id") or "").strip()
    if explicit:
        sid = slugify_tariff_id(explicit)
        if not sid or sid == "tariff":
            raise ValueError(
                f"Tarif '{tariff_id}': supplier_id ist leer oder ungültig."
            )
        return sid
    mapped = _SUPPLIER_ID_BY_TARIFF_ID.get(tariff_id)
    if mapped:
        return mapped
    sid = _supplier_id_from_label(label)
    if not sid or sid == "tariff":
        raise ValueError(f"Tarif '{tariff_id}': supplier_id fehlt.")
    return sid


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
        "monthly_fee_eur",
        "grid_monthly_fee_eur",
        "metering_monthly_fee_eur",
        "other_monthly_fee_eur",
    ):
        value = _optional_float(raw, key)
        if value is not None:
            spec[key] = value
    if "prices_include_vat" in raw:
        spec["prices_include_vat"] = bool(raw["prices_include_vat"])
    notes = raw.get("notes")
    if notes is not None and str(notes).strip():
        spec["notes"] = str(notes).strip()


def _copy_spot_export_fee_fields(raw: dict, spec: dict) -> None:
    for key in _SPOT_EXPORT_FEE_KEYS:
        if key in raw and raw[key] is not None:
            spec[key] = float(raw[key])


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
    spec["supplier_id"] = resolve_supplier_id(raw, tariff_id=tariff_id, label=label)
    if tariff_type == "fixed_cent":
        if "fix_cent_kwh" not in raw:
            raise ValueError(
                f"import_tariffs[{index}] ('{tariff_id}'): price_cent_kwh fehlt."
            )
        spec["fix_cent_kwh"] = float(raw["fix_cent_kwh"])
    elif tariff_type == "monthly_table":
        rates = raw.get("monthly_rates")
        if not isinstance(rates, list):
            raise ValueError(
                f"import_tariffs[{index}] ('{tariff_id}'): monthly_rates fehlt."
            )
        spec["monthly_rates"] = validate_fixed_monthly_feed_in_rates(rates)
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
    spec["supplier_id"] = resolve_supplier_id(raw, tariff_id=tariff_id, label=label)
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
    elif tariff_type in {"spot_hourly", "ex_post_spot"}:
        if "land" not in spec:
            raise ValueError(
                f"export_tariffs[{index}] ('{tariff_id}'): land fehlt für {tariff_type}."
            )
        _copy_spot_export_fee_fields(raw, spec)
    return spec


def _normalize_import_tariff(raw: dict, index: int) -> dict:
    return _import_tariff_spec(raw, index)


def _normalize_export_tariff(raw: dict, index: int) -> dict:
    return _export_tariff_spec(raw, index)


def _reject_legacy_tariff_types(
    items: list,
    *,
    aliases: dict[str, str],
    kind: str,
) -> None:
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        tariff_type = str(item.get("type", "")).strip().lower()
        replacement = aliases.get(tariff_type)
        if not replacement:
            continue
        tariff_id = str(item.get("id", "")).strip() or f"{kind}[{index}]"
        raise ValueError(
            f"{kind} '{tariff_id}': type '{tariff_type}' ist nicht mehr unterstützt "
            f"— bitte '{replacement}' verwenden."
        )


def reject_export_monthly_float_in_doc(doc: dict) -> None:
    """Reject legacy export type monthly_float (use monthly_table)."""
    exports = doc.get("export_tariffs")
    if not isinstance(exports, list):
        return
    for index, item in enumerate(exports):
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).strip().lower() != "monthly_float":
            continue
        tariff_id = str(item.get("id", "")).strip() or f"index_{index}"
        raise ValueError(
            f"export_tariffs '{tariff_id}': type 'monthly_float' ist nicht mehr "
            "unterstützt — bitte 'monthly_table' verwenden."
        )


def reject_legacy_spot_types_in_doc(doc: dict) -> None:
    """Reject legacy types awattar / dynamic_epex (use spot_hourly)."""
    imports = doc.get("import_tariffs")
    if isinstance(imports, list):
        _reject_legacy_tariff_types(
            imports, aliases=_LEGACY_IMPORT_TYPES, kind="import_tariffs"
        )
    exports = doc.get("export_tariffs")
    if isinstance(exports, list):
        _reject_legacy_tariff_types(
            exports, aliases=_LEGACY_EXPORT_TYPES, kind="export_tariffs"
        )


def normalize_tariffs_document(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("tariffs.json muss ein Objekt sein.")
    imports_raw = doc.get("import_tariffs", [])
    exports_raw = doc.get("export_tariffs", [])
    if not isinstance(imports_raw, list):
        raise ValueError("import_tariffs muss ein Array sein.")
    if not isinstance(exports_raw, list):
        raise ValueError("export_tariffs muss ein Array sein.")
    reject_legacy_spot_types_in_doc(doc)
    reject_export_monthly_float_in_doc(doc)
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
    elif tariff["type"] in {"spot_hourly", "ex_post_spot"}:
        out["feed_in_mode"] = "dynamic_epex"
        out["k_push_cent"] = float(out.get("k_push_cent", 0.0) or 0.0)
    elif tariff["type"] == "monthly_table":
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = float(out.get("k_push_cent", 0.0) or 0.0)
        if monthly_rates_holder is not None:
            rates = tariff["monthly_rates"]
            # Normalized catalog: tuple[(y,m,cent),...]; raw JSON: list[dict].
            if isinstance(rates, tuple) and (
                not rates or isinstance(rates[0], tuple)
            ):
                validated = rates
            else:
                validated = validate_fixed_monthly_feed_in_rates(rates)
            monthly_rates_holder["_monthly_fixed_tariffs"] = validated
    return out


def append_monthly_rate(
    path: str,
    *,
    side: str,
    tariff_id: str,
    year: int,
    month: int,
    tariff_cent_kwh: float,
) -> None:
    """Append or replace one monthly_rates row on a raw list-shaped tariffs.json.

    ``side`` is ``import`` or ``export``. Does not write normalized id-maps.
    """
    from settings.json_io import write_json_dict

    side_key = str(side).strip().lower()
    if side_key == "import":
        list_key = "import_tariffs"
    elif side_key == "export":
        list_key = "export_tariffs"
    else:
        raise ValueError("side muss 'import' oder 'export' sein.")

    year_i = int(year)
    month_i = int(month)
    cent = float(tariff_cent_kwh)
    if month_i < 1 or month_i > 12:
        raise ValueError("month muss 1–12 sein.")
    if cent <= 0.0:
        raise ValueError("tariff_cent_kwh muss > 0 sein.")

    doc = _read_json(path)
    tariffs = doc.get(list_key)
    if not isinstance(tariffs, list):
        raise ValueError(
            f"{list_key} muss ein Array in tariffs.json sein (nicht normalisierte Map)."
        )

    want_id = str(tariff_id).strip()
    if side_key == "export":
        want_id = resolve_export_tariff_id(want_id)

    target: dict | None = None
    for entry in tariffs:
        if isinstance(entry, dict) and str(entry.get("id", "")).strip() == want_id:
            target = entry
            break
    if target is None:
        raise ValueError(f"Unbekannte {side_key}_tariff_id '{want_id}'.")

    tariff_type = str(target.get("type", "")).strip().lower()
    if tariff_type != "monthly_table":
        raise ValueError(
            f"Tarif '{want_id}' hat type '{tariff_type}' — "
            "nur monthly_table erlaubt Monatseinträge."
        )

    rates = target.get("monthly_rates")
    if rates is None:
        rates = []
        target["monthly_rates"] = rates
    if not isinstance(rates, list):
        raise ValueError(f"Tarif '{want_id}': monthly_rates muss ein Array sein.")

    new_row = {
        "year": year_i,
        "month": month_i,
        "tariff_cent_kwh": cent,
    }
    replaced = False
    for index, row in enumerate(rates):
        if (
            isinstance(row, dict)
            and int(row.get("year", -1)) == year_i
            and int(row.get("month", -1)) == month_i
        ):
            rates[index] = new_row
            replaced = True
            break
    if not replaced:
        rates.append(new_row)

    validate_fixed_monthly_feed_in_rates(rates)
    write_json_dict(path, doc)
