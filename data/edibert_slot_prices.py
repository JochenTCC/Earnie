"""Slot prices from Edibert (Edibert P3a; the only pricing path since P3b).

Maps Earnie's slot lists (``slot_datetimes`` + EPEX cent/kWh) to Edibert's
``tariff_price_series`` and back, so the seams get ``k_act`` / ``k_push_act`` lists in the
same order as their input. No model change: the MILP keeps receiving cent per slot.

Which tariff, grid fee and pricing context apply comes from the *pricing reference*
(:func:`pricing_reference`), a plain dict that the scenario resolution stores under
:data:`EDIBERT_PRICING_KEY`. Edibert loads the tariff and grid files itself.

Consecutive 15-min slots are priced as one series, so hourly settled spot tariffs get
Edibert's own hourly mean. When the input covers an hour only partly (a horizon that starts
or ends mid-hour), the caller's ``market_for`` supplies the market prices of the missing
quarter-hours (Edibert P3b decision D1); without it the partial hour is Edibert's
``PRICE_MISSING`` — an error, never a guess.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from house_config import edibert_tariffs as eb

logger = logging.getLogger(__name__)

EDIBERT_PRICING_KEY = "_edibert_pricing"
_SLOT = timedelta(minutes=15)
_LOGGED_WARNINGS: set[tuple[str, str]] = set()

# Market prices (cent/kWh) for extra quarter-hours, given as local, tz-aware slot starts.
MarketFor = Callable[[list[datetime]], Sequence[float | None]]


def pricing_reference(
    *,
    tariffs_path: str,
    grid_fees_path: str | None,
    import_tariff_id: str | None,
    export_tariff_id: str | None,
    timezone_name: str,
    profile: dict | None,
    user_fixed: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """What Edibert needs to price a scenario: file paths, tariff IDs, profile location.

    ``__user_fixed__`` (*Eigener Festpreis*) is no file tariff: ``user_fixed[direction]`` holds
    its ``cent`` and ``vat_percent`` from the resolved scenario; missing values are an error.
    """
    fixed: dict[str, dict[str, float]] = {}
    for direction, tariff_id in ((eb.IMPORT, import_tariff_id), (eb.EXPORT, export_tariff_id)):
        if str(tariff_id or "").strip() != eb.USER_FIXED_ID:
            continue
        values = (user_fixed or {}).get(direction)
        if not values or "cent" not in values or "vat_percent" not in values:
            raise ValueError(
                f"Edibert-Preisreferenz: Eigener Festpreis ({direction}) ohne cent/vat_percent."
            )
        fixed[direction] = {"cent": float(values["cent"]), "vat_percent": float(values["vat_percent"])}
    profile = profile if isinstance(profile, dict) else {}
    netznutzung = profile.get("netznutzung")
    return {
        "tariffs_path": str(tariffs_path),
        "grid_fees_path": str(grid_fees_path) if grid_fees_path else None,
        "import_tariff_id": str(import_tariff_id).strip() if import_tariff_id else None,
        "export_tariff_id": str(export_tariff_id).strip() if export_tariff_id else None,
        "timezone_name": str(timezone_name),
        "land": str(profile.get("land", "") or "").strip() or None,
        "region": str(profile.get("region", "") or "").strip() or None,
        "netznutzung": dict(netznutzung) if isinstance(netznutzung, dict) else None,
        "user_fixed": fixed,
    }


def require_pricing_reference(source: dict | None, *, where: str) -> dict[str, Any]:
    """The pricing reference of resolved settings; missing means a path bypassed resolution."""
    ref = (source or {}).get(EDIBERT_PRICING_KEY) if isinstance(source, dict) else None
    if not isinstance(ref, dict):
        raise ValueError(
            f"{where} hat keine Edibert-Preisreferenz ({EDIBERT_PRICING_KEY}); "
            "Einstellungen wurden ohne Szenario-Auflösung gebaut."
        )
    return ref


def pricing_context(ref: dict[str, Any]) -> Any:
    return eb.pricing_context_for_profile(
        "Preisreferenz",
        {"timezone_name": ref["timezone_name"], "land": ref["land"], "region": ref["region"]},
    )


def grid_fee(ref: dict[str, Any]) -> Any:
    """Resolved Edibert ``GridFee`` of the reference; ``None`` without ``netznutzung``."""
    if ref.get("netznutzung") is None:
        return None
    if not ref.get("grid_fees_path"):
        raise ValueError("Edibert-Preisreferenz: netznutzung gesetzt, aber kein grid_fees_path.")
    catalog = eb.cached_grid_fees(ref["grid_fees_path"])
    return eb.profile_grid_fee("Preisreferenz", {"netznutzung": ref["netznutzung"]}, catalog)


def tariff(ref: dict[str, Any], direction: str) -> Any:
    """Edibert ``Tariff`` of one direction (catalog / user file, or *Eigener Festpreis*)."""
    key = "import_tariff_id" if direction == eb.IMPORT else "export_tariff_id"
    tariff_id = ref.get(key)
    if not tariff_id:
        raise ValueError(f"Edibert-Preisreferenz: {key} fehlt.")
    if tariff_id == eb.USER_FIXED_ID:
        values = ref["user_fixed"][direction]
        return eb.synthetic_fixed_tariff(
            direction, values["cent"], vat_percent=values["vat_percent"], land=ref["land"]
        )
    return eb.tariff_by_id(eb.cached_tariff_set(ref["tariffs_path"]), direction, tariff_id)


def _runs(utc_slots: Sequence[datetime]) -> list[tuple[int, int]]:
    """Index ranges ``[i, j)`` of consecutive 15-min slots."""
    runs: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(utc_slots) + 1):
        if index == len(utc_slots) or utc_slots[index] - utc_slots[index - 1] != _SLOT:
            runs.append((start, index))
            start = index
    return runs


def _log_warnings(tariff_id: str, warnings: Sequence[Any]) -> None:
    for warning in warnings:
        text = eb.warning_text(warning)
        if (tariff_id, text) in _LOGGED_WARNINGS:
            continue
        _LOGGED_WARNINGS.add((tariff_id, text))
        logger.warning("Edibert-Tarif %s: %s", tariff_id, text)


def _hour_quarters(slot_utc: datetime, ctx: Any) -> list[datetime]:
    """The four UTC slot starts of the local hour of ``slot_utc`` (Edibert's hourly mean)."""
    hour = ctx.to_local(slot_utc).replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    return [hour + _SLOT * index for index in range(4)]


def _fill_partial_hours(
    tariff_obj: Any,
    ctx: Any,
    utc_slots: Sequence[datetime],
    market: dict[datetime, float],
    market_for: MarketFor | None,
) -> None:
    """D1: market prices for the quarter-hours an hourly settled tariff needs but the input lacks."""
    if not (tariff_obj.is_spot and tariff_obj.settlement_mtu == "60min"):
        return
    wanted = sorted(
        {quarter for slot in utc_slots for quarter in _hour_quarters(slot, ctx)} - set(utc_slots)
    )
    if not wanted or market_for is None:
        return  # a slot without its hour stays PRICE_MISSING in Edibert
    local = [ctx.to_local(quarter) for quarter in wanted]
    values = list(market_for(local))
    if len(values) != len(wanted):
        raise ValueError("market_for muss je angefragtem Slot genau einen Preis liefern.")
    for quarter, value in zip(wanted, values):
        if value is not None:
            market[quarter] = float(value)


def price_points(
    direction: str,
    slot_datetimes: Sequence[datetime],
    epex_values: Sequence[float | None],
    ref: dict[str, Any],
    *,
    market_for: MarketFor | None = None,
    warnings_out: list[str] | None = None,
) -> list[Any]:
    """Edibert ``PricePoint`` per input slot, in input order (naive slots = house time).

    ``market_for`` supplies market prices for quarter-hours outside the input that an hourly
    settled tariff needs (D1). Warnings are logged once per tariff; ``warnings_out`` also
    collects them (reports).
    """
    if len(slot_datetimes) != len(epex_values):
        raise ValueError("slot_datetimes und epex_values müssen gleich lang sein.")
    if not slot_datetimes:
        return []
    ctx = pricing_context(ref)
    tariff_obj = tariff(ref, direction)
    fee = grid_fee(ref) if direction == eb.IMPORT else None
    utc_slots = [ctx.to_local(slot).astimezone(UTC) for slot in slot_datetimes]
    market = {
        slot: float(value)
        for slot, value in zip(utc_slots, epex_values)
        if value is not None
    }
    _fill_partial_hours(tariff_obj, ctx, utc_slots, market, market_for)
    points: list[Any] = []
    for start, end in _runs(utc_slots):
        series = eb.price_series(
            tariff_obj,
            ctx,
            utc_slots[start],
            utc_slots[end - 1] + _SLOT,
            market=market,
            grid_fee=fee,
        )
        _log_warnings(tariff_obj.id, series.warnings)
        if warnings_out is not None:
            warnings_out.extend(eb.warning_text(warning) for warning in series.warnings)
        points.extend(series.points)
    return points


def import_cents(
    slot_datetimes: Sequence[datetime],
    epex_values: Sequence[float | None],
    ref: dict[str, Any],
    *,
    market_for: MarketFor | None = None,
) -> list[float]:
    """``k_act`` per slot (cent/kWh incl. grid fee and VAT)."""
    points = price_points(
        eb.IMPORT, slot_datetimes, epex_values, ref, market_for=market_for
    )
    return [point.cent for point in points]


def export_cents(
    slot_datetimes: Sequence[datetime],
    epex_values: Sequence[float | None],
    ref: dict[str, Any],
    *,
    market_for: MarketFor | None = None,
) -> list[float]:
    """``k_push_act`` per slot (cent/kWh)."""
    points = price_points(
        eb.EXPORT, slot_datetimes, epex_values, ref, market_for=market_for
    )
    return [point.cent for point in points]


def single_slot_cent(
    direction: str, slot: datetime, epex_cent: float | None, ref: dict[str, Any]
) -> float:
    """One slot priced on its own quarter-hour market price (no hourly mean).

    Only for converting legacy log entries in the history chart, which stored a single EPEX
    value per slot; planning always prices whole lists (:func:`import_cents`).
    """
    ctx = pricing_context(ref)
    tariff_obj = tariff(ref, direction)
    fee = grid_fee(ref) if direction == eb.IMPORT else None
    result = eb.evaluate_slot(
        tariff_obj,
        ctx.to_local(slot).astimezone(UTC),
        ctx,
        epex_cent=None if epex_cent is None else float(epex_cent),
        grid_fee=fee,
    )
    return float(result.cent)


def _read_json_or_empty(path: str | None) -> dict[str, Any]:
    import json
    import os

    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8-sig") as handle:
        doc = json.load(handle)
    return doc if isinstance(doc, dict) else {}


def _entry_by_id(items: Any, entry_id: str) -> Any:
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("id", "")).strip() == entry_id:
            return item
    return None


def pricing_digest(ref: dict[str, Any]) -> str:
    """Hash of everything a price depends on: the reference, the raw tariff entries, the grid
    area and its rule set (from catalog and user files).

    Part of the SE fingerprint, so a changed catalog entry (e.g. a new time-window rule)
    invalidates cached results even when the tariff ID stays the same.
    """
    import hashlib
    import json

    from runtime_store.persist_paths import user_grid_fees_path_for, user_tariffs_path_for

    # File paths are left out: the same content in another directory prices the same.
    payload: dict[str, Any] = {
        "ref": {k: v for k, v in ref.items() if k not in ("tariffs_path", "grid_fees_path")}
    }
    tariff_docs = [
        _read_json_or_empty(ref.get("tariffs_path")),
        _read_json_or_empty(user_tariffs_path_for(ref["tariffs_path"])),
    ]
    for key, section in (("import_tariff_id", "import_tariffs"), ("export_tariff_id", "export_tariffs")):
        tariff_id = ref.get(key)
        if tariff_id and tariff_id != eb.USER_FIXED_ID:
            payload[key] = [_entry_by_id(doc.get(section), tariff_id) for doc in tariff_docs]
    area_id = (ref.get("netznutzung") or {}).get("area_id")
    if area_id and ref.get("grid_fees_path"):
        grid_docs = [
            _read_json_or_empty(ref["grid_fees_path"]),
            _read_json_or_empty(user_grid_fees_path_for(ref["grid_fees_path"])),
        ]
        areas = [_entry_by_id(doc.get("areas"), area_id) for doc in grid_docs]
        rule_set = next((a.get("rule_set") for a in areas if isinstance(a, dict)), None)
        payload["grid_area"] = areas
        if rule_set:
            payload["rule_set"] = [(doc.get("rule_sets") or {}).get(rule_set) for doc in grid_docs]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
