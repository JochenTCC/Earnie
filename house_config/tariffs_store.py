"""Laden und Validieren von config/tariffs.json."""
from __future__ import annotations

import json
import logging
import os
import re

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates
from data.tariff_pricing import STANDARD_VAT_PERCENT_BY_LAND, market_zone_for_land

logger = logging.getLogger(__name__)

_warned_ignored_settlement_fee: set[str] = set()
_warned_gross_without_vat: set[str] = set()

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

# Scenario-local fixed price (not a tariffs.json catalog id).
USER_FIXED_TARIFF_ID = "__user_fixed__"
USER_FIXED_TARIFF_LABEL = "Eigener Festpreis"
USER_IMPORT_CENT_KEY = "user_import_cent_kwh"
USER_EXPORT_CENT_KEY = "user_export_cent_kwh"


def is_user_fixed_tariff_id(tariff_id: str | None) -> bool:
    return str(tariff_id or "").strip() == USER_FIXED_TARIFF_ID


def user_fixed_pseudo_tariff() -> dict:
    """Dropdown entry for scenario-local fixed prices (not in tariffs.json)."""
    return {
        "id": USER_FIXED_TARIFF_ID,
        "label": USER_FIXED_TARIFF_LABEL,
        "type": "fixed_cent",
        "supplier_id": "user",
    }


def ensure_user_fixed_option(tariffs: list[dict]) -> list[dict]:
    """Append Eigener Festpreis if missing (always visible in dropdowns)."""
    if any(is_user_fixed_tariff_id(item.get("id")) for item in tariffs):
        return list(tariffs)
    return [*tariffs, user_fixed_pseudo_tariff()]


def _parse_user_import_cent(settings: dict) -> float:
    if USER_IMPORT_CENT_KEY not in settings or settings[USER_IMPORT_CENT_KEY] is None:
        raise ValueError(
            f"import_tariff_id '{USER_FIXED_TARIFF_ID}' erfordert {USER_IMPORT_CENT_KEY}."
        )
    value = float(settings[USER_IMPORT_CENT_KEY])
    if value <= 0.0:
        raise ValueError(f"{USER_IMPORT_CENT_KEY} muss > 0 sein.")
    return value


def _parse_user_export_cent(settings: dict) -> float:
    if USER_EXPORT_CENT_KEY not in settings or settings[USER_EXPORT_CENT_KEY] is None:
        raise ValueError(
            f"export_tariff_id '{USER_FIXED_TARIFF_ID}' erfordert {USER_EXPORT_CENT_KEY}."
        )
    value = float(settings[USER_EXPORT_CENT_KEY])
    if value < 0.0:
        raise ValueError(f"{USER_EXPORT_CENT_KEY} muss >= 0 sein.")
    return value


def _synthetic_user_import_tariff(cent: float) -> dict:
    return {
        "id": USER_FIXED_TARIFF_ID,
        "label": USER_FIXED_TARIFF_LABEL,
        "type": "fixed_cent",
        "fix_cent_kwh": float(cent),
        "prices_include_vat": True,
        "vat_percent": 0.0,
        "supplier_id": "user",
    }


def apply_land_vat_to_user_fixed_import(settings: dict, land: str) -> dict:
    """Give the user-fixed import price the VAT rate of the house profile's land.

    The price is entered gross, but the net Netznutzung must get VAT on top, so the
    tariff needs a rate. Other tariffs carry their own ``vat_percent``.
    """
    spec = settings.get("_import_tariff_spec")
    if not isinstance(spec, dict) or not is_user_fixed_tariff_id(spec.get("id")):
        return settings
    land_key = str(land or "").strip().upper()
    if land_key not in STANDARD_VAT_PERCENT_BY_LAND:
        raise ValueError(f"Keine Standard-USt für Land {land!r} (AT, DE oder CH).")
    out = dict(settings)
    out["_import_tariff_spec"] = {
        **spec,
        "vat_percent": STANDARD_VAT_PERCENT_BY_LAND[land_key],
    }
    return out


def _synthetic_user_export_tariff(cent: float) -> dict:
    return {
        "id": USER_FIXED_TARIFF_ID,
        "label": USER_FIXED_TARIFF_LABEL,
        "type": "fixed",
        "k_push_cent": float(cent),
        "prices_include_vat": True,
        "vat_percent": 0.0,
        "supplier_id": "user",
    }


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
    if "settlement_mtu" in raw and raw["settlement_mtu"] is not None:
        settlement_mtu = str(raw["settlement_mtu"]).strip().lower()
        if settlement_mtu not in ("15min", "60min"):
            raise ValueError(
                f"settlement_mtu muss '15min' oder '60min' sein, nicht {raw['settlement_mtu']!r}."
            )
        spec["settlement_mtu"] = settlement_mtu
    notes = raw.get("notes")
    if notes is not None and str(notes).strip():
        spec["notes"] = str(notes).strip()


def _copy_spot_export_fee_fields(raw: dict, spec: dict) -> None:
    for key in _SPOT_EXPORT_FEE_KEYS:
        if key in raw and raw[key] is not None:
            spec[key] = float(raw[key])


def _require_land(spec: dict, *, kind: str, index: int) -> None:
    if "land" not in spec:
        raise ValueError(
            f"{kind}[{index}] ('{spec['id']}'): land fehlt (AT, DE oder CH). "
            "Jeder Tarif braucht ein Land, damit der Land-Filter im "
            "Szenarienkonfigurator ihn nicht ausblendet."
        )


def _warn_ignored_settlement_fee(spec: dict) -> None:
    """Warn once per tariff: the fee only applies to spot import types."""
    fee = spec.get("settlement_fee_cent_kwh")
    if not fee or spec["type"] not in ("fixed_cent", "monthly_table"):
        return
    tariff_id = spec["id"]
    if tariff_id in _warned_ignored_settlement_fee:
        return
    _warned_ignored_settlement_fee.add(tariff_id)
    logger.warning(
        "Tarif '%s' (%s): settlement_fee_cent_kwh=%s hat bei diesem Typ keine Wirkung "
        "(nur Spot-Tarife). Netzkosten gehören in 'netznutzung' am Hausprofil.",
        tariff_id,
        spec["type"],
        fee,
    )


def _warn_gross_import_without_vat(spec: dict) -> None:
    """Warn once per tariff: Netznutzung (net) gets no VAT without a rate."""
    if not spec.get("prices_include_vat", True) or spec.get("vat_percent"):
        return
    tariff_id = spec["id"]
    if tariff_id in _warned_gross_without_vat:
        return
    _warned_gross_without_vat.add(tariff_id)
    logger.warning(
        "Tarif '%s': prices_include_vat ist wahr, aber vat_percent fehlt oder ist 0 — "
        "die Netznutzung (netto) wird ohne USt addiert. vat_percent setzen (z. B. 20).",
        tariff_id,
    )


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
    _require_land(spec, kind="import_tariffs", index=index)
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
    _warn_ignored_settlement_fee(spec)
    _warn_gross_import_without_vat(spec)
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
    _require_land(spec, kind="export_tariffs", index=index)
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
    """``tariffs.json`` plus the Edibert user file ``user_tariffs.json`` next to it (if present).

    Both are tariff-track files: an existing file without the current ``tariff_format`` is
    rejected with the migration hint (Edibert P2).
    """
    from runtime_store.data_model import ensure_tariff_format
    from runtime_store.persist_paths import user_tariffs_path_for

    doc = _read_json(path)
    if os.path.isfile(path):
        ensure_tariff_format(doc, label=f"tariffs.json ({path})")
    normalized = normalize_tariffs_document(doc)
    user_path = user_tariffs_path_for(path)
    if os.path.isfile(user_path):
        merge_user_tariffs(normalized, user_path)
    return normalized


# --- Edibert user tariffs (user_tariffs.json, Edibert P1) ---------------------------

ORIGIN_KEY = "origin"
ORIGIN_USER = "user"
ENGINE_PENDING_KEY = "engine_pending_fields"
# Fields Earnie's own engine prices with or carries as metadata.
_EARNIE_ENGINE_FIELDS = frozenset(
    {
        "id", "label", "type", "land", "currency", "supplier_id", "notes",
        "settlement_fee_cent_kwh", "markup_percent", "prices_include_vat", "vat_percent",
        "settlement_mtu", "fix_cent_kwh", "k_push_cent", "monthly_rates", "monthly_seed",
        "feed_in_fee_factor", "feed_in_fix_cent", "monthly_fee_eur", "grid_monthly_fee_eur",
        "metering_monthly_fee_eur", "other_monthly_fee_eur",
    }
)  # fmt: skip
# Edibert fields without price effect (display / metadata only).
_EDIBERT_DISPLAY_FIELDS = frozenset(
    {"$comment", "requires", "behavior_notes", "source", "last_verified", "individual", "applies_to"}
)
# Only change a price through rules; without rules they have no effect.
_RULE_MODIFIER_FIELDS = frozenset({"holidays", "extra_holiday_dates"})


def engine_pending_fields(raw: dict) -> tuple[str, ...]:
    """Fields of a user tariff that Earnie's engine cannot price yet (until Edibert P3b).

    Allowlist: every field that is neither priced by Earnie nor display-only counts, so a
    field added to Edibert later is never ignored silently.
    """
    pending: list[str] = []
    for key, value in raw.items():
        if key in _EARNIE_ENGINE_FIELDS or key in _EDIBERT_DISPLAY_FIELDS:
            continue
        if key == "rules" and not value:
            continue
        if key in _RULE_MODIFIER_FIELDS and not raw.get("rules"):
            continue
        pending.append(key)
    return tuple(sorted(pending))


def is_engine_pending(tariff: dict) -> bool:
    return bool(tariff.get(ENGINE_PENDING_KEY))


def tariff_display_label(tariff: dict) -> str:
    """Selection label: user tariffs are marked, unpriceable ones say so."""
    label = str(tariff.get("label") or tariff.get("id") or "").strip()
    if tariff.get(ORIGIN_KEY) != ORIGIN_USER:
        return label
    if is_engine_pending(tariff):
        return f"{label} · Benutzertarif, erst ab Engine-Umstellung"
    return f"{label} · Benutzertarif"


def _pending_user_spec(raw: dict, kind: str, index: int, pending: tuple[str, ...]) -> dict:
    """Selection entry for a user tariff Earnie cannot price yet (no engine fields)."""
    tariff_id = str(raw.get("id", "")).strip()
    tariff_type = str(raw.get("type", "")).strip().lower()
    label = str(raw.get("label", tariff_id)).strip() or tariff_id
    spec: dict = {"id": tariff_id, "label": label, "type": tariff_type}
    _normalize_dach_fields(raw, spec)
    _require_land(spec, kind=kind, index=index)
    spec["supplier_id"] = resolve_supplier_id(raw, tariff_id=tariff_id, label=label)
    spec[ENGINE_PENDING_KEY] = pending
    return spec


def _merge_user_section(
    target: dict[str, dict], items: object, *, kind: str, user_path: str
) -> None:
    if items is None:
        return
    if not isinstance(items, list):
        raise ValueError(f"user_tariffs.json: {kind} muss ein Array sein.")
    build = _import_tariff_spec if kind == "import_tariffs" else _export_tariff_spec
    for index, raw in enumerate(items):
        pending = engine_pending_fields(raw)
        try:
            spec = (
                _pending_user_spec(raw, kind, index, pending)
                if pending
                else build(raw, index)
            )
        except ValueError as exc:
            raise ValueError(f"user_tariffs.json ({user_path}): {exc}") from exc
        if spec["id"] in target:
            raise ValueError(
                f"user_tariffs.json: {kind} '{spec['id']}' gibt es schon in tariffs.json."
            )
        spec[ORIGIN_KEY] = ORIGIN_USER
        target[spec["id"]] = spec


def merge_user_tariffs(normalized: dict, user_path: str) -> None:
    """Add the user tariffs to a normalized catalog; Edibert checks the file first (fail loud)."""
    from house_config.edibert_tariffs import load_user_tariff_set

    load_user_tariff_set(user_path)
    doc = _read_json(user_path)
    _merge_user_section(
        normalized["import_tariffs"], doc.get("import_tariffs"),
        kind="import_tariffs", user_path=user_path,
    )  # fmt: skip
    _merge_user_section(
        normalized["export_tariffs"], doc.get("export_tariffs"),
        kind="export_tariffs", user_path=user_path,
    )  # fmt: skip


def _reject_engine_pending(tariff: dict, *, side: str) -> None:
    if not is_engine_pending(tariff):
        return
    fields = ", ".join(tariff[ENGINE_PENDING_KEY])
    raise ValueError(
        f"{side} '{tariff['id']}' ist ein Benutzertarif mit {fields} — Earnie kann ihn erst "
        "nach der Engine-Umstellung auf Edibert bepreisen. Bitte vorerst einen anderen "
        "Tarif wählen."
    )


def resolve_import_tariff_into_settings(settings: dict, tariffs: dict) -> dict:
    out = dict(settings)
    tariff_id = out.pop("import_tariff_id", None)
    if not tariff_id:
        out.pop(USER_IMPORT_CENT_KEY, None)
        return out
    tariff_id = str(tariff_id).strip()
    if is_user_fixed_tariff_id(tariff_id):
        cent = _parse_user_import_cent(out)
        out.pop(USER_IMPORT_CENT_KEY, None)
        tariff = _synthetic_user_import_tariff(cent)
        out["_import_tariff_spec"] = tariff
        out["import_tariff_type"] = tariff["type"]
        out["import_fixed_cent_kwh"] = tariff["fix_cent_kwh"]
        return out
    out.pop(USER_IMPORT_CENT_KEY, None)
    import_map = tariffs.get("import_tariffs", {})
    if tariff_id not in import_map:
        raise ValueError(f"Unbekannte import_tariff_id '{tariff_id}'.")
    tariff = dict(import_map[tariff_id])
    _reject_engine_pending(tariff, side="Bezugstarif")
    out["_import_tariff_spec"] = tariff
    out["import_tariff_type"] = tariff["type"]
    if tariff["type"] == "fixed_cent":
        out["import_fixed_cent_kwh"] = tariff["fix_cent_kwh"]
    if "land" in tariff:
        out["market_zone"] = market_zone_for_land(tariff["land"])
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
        out.pop(USER_EXPORT_CENT_KEY, None)
        return out
    tariff_id = resolve_export_tariff_id(str(tariff_id).strip())
    if is_user_fixed_tariff_id(tariff_id):
        cent = _parse_user_export_cent(out)
        out.pop(USER_EXPORT_CENT_KEY, None)
        tariff = _synthetic_user_export_tariff(cent)
        out["_export_tariff_spec"] = tariff
        out["feed_in_mode"] = "fixed"
        out["k_push_cent"] = tariff["k_push_cent"]
        return out
    out.pop(USER_EXPORT_CENT_KEY, None)
    export_map = tariffs.get("export_tariffs", {})
    if tariff_id not in export_map:
        raise ValueError(f"Unbekannte export_tariff_id '{tariff_id}'.")
    tariff = dict(export_map[tariff_id])
    _reject_engine_pending(tariff, side="Einspeisetarif")
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


def _validate_monthly_rate_args(
    *,
    side: str,
    year: int,
    month: int,
    tariff_cent_kwh: float,
) -> tuple[str, str, int, int, float]:
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
    return side_key, list_key, year_i, month_i, cent


def _find_monthly_table_tariff(
    tariffs: list,
    *,
    side_key: str,
    want_id: str,
) -> dict:
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
    return target


def _upsert_monthly_rate_row(
    rates: list,
    *,
    year_i: int,
    month_i: int,
    cent: float,
) -> None:
    new_row = {
        "year": year_i,
        "month": month_i,
        "tariff_cent_kwh": cent,
    }
    for index, row in enumerate(rates):
        if (
            isinstance(row, dict)
            and int(row.get("year", -1)) == year_i
            and int(row.get("month", -1)) == month_i
        ):
            rates[index] = new_row
            return
    rates.append(new_row)


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

    side_key, list_key, year_i, month_i, cent = _validate_monthly_rate_args(
        side=side, year=year, month=month, tariff_cent_kwh=tariff_cent_kwh
    )
    doc = _read_json(path)
    tariffs = doc.get(list_key)
    if not isinstance(tariffs, list):
        raise ValueError(
            f"{list_key} muss ein Array in tariffs.json sein (nicht normalisierte Map)."
        )
    want_id = str(tariff_id).strip()
    if side_key == "export":
        want_id = resolve_export_tariff_id(want_id)
    target = _find_monthly_table_tariff(tariffs, side_key=side_key, want_id=want_id)
    rates = target.get("monthly_rates")
    if rates is None:
        rates = []
        target["monthly_rates"] = rates
    if not isinstance(rates, list):
        raise ValueError(f"Tarif '{want_id}': monthly_rates muss ein Array sein.")
    _upsert_monthly_rate_row(rates, year_i=year_i, month_i=month_i, cent=cent)
    validate_fixed_monthly_feed_in_rates(rates)
    write_json_dict(path, doc)
