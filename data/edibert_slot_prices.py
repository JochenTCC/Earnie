"""Slot prices from Edibert (Edibert P3a; the default path from P3b on).

Maps Earnie's slot lists (``slot_datetimes`` + EPEX cent/kWh) to Edibert's
``tariff_price_series`` and back, so the seams get ``k_act`` / ``k_push_act`` lists in the
same order as their input. No model change: the MILP keeps receiving cent per slot.

Which tariff, grid fee and pricing context apply comes from the *pricing reference*
(:func:`pricing_reference`), a plain dict that the scenario resolution stores under
:data:`EDIBERT_PRICING_KEY` when ``EARNIE_PRICING_ENGINE=edibert``. Edibert loads the
tariff and grid files itself; Earnie's normalized specs are not used on this path.

Consecutive 15-min slots are priced as one series, so hourly settled spot tariffs get
Edibert's own hourly mean (Earnie's pre-averaging is not applied here). An hour that the
input covers only partly is Edibert's ``PRICE_MISSING`` — an error, never a guess.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from house_config import edibert_tariffs as eb

logger = logging.getLogger(__name__)

EDIBERT_PRICING_KEY = "_edibert_pricing"
_SLOT = timedelta(minutes=15)
_LOGGED_WARNINGS: set[tuple[str, str]] = set()


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
    from house_config.tariffs_store import is_user_fixed_tariff_id

    fixed: dict[str, dict[str, float]] = {}
    for direction, tariff_id in ((eb.IMPORT, import_tariff_id), (eb.EXPORT, export_tariff_id)):
        if not is_user_fixed_tariff_id(tariff_id):
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
            f"EARNIE_PRICING_ENGINE=edibert: {where} hat keine Edibert-Preisreferenz "
            f"({EDIBERT_PRICING_KEY}); Einstellungen wurden ohne Szenario-Auflösung gebaut."
        )
    return ref


def _context(ref: dict[str, Any]) -> Any:
    return eb.pricing_context_for_profile(
        "Preisreferenz",
        {"timezone_name": ref["timezone_name"], "land": ref["land"], "region": ref["region"]},
    )


def _grid_fee(ref: dict[str, Any]) -> Any:
    if ref.get("netznutzung") is None:
        return None
    if not ref.get("grid_fees_path"):
        raise ValueError("Edibert-Preisreferenz: netznutzung gesetzt, aber kein grid_fees_path.")
    catalog = eb.cached_grid_fees(ref["grid_fees_path"])
    return eb.profile_grid_fee("Preisreferenz", {"netznutzung": ref["netznutzung"]}, catalog)


def _tariff(ref: dict[str, Any], direction: str) -> Any:
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


def price_points(
    direction: str,
    slot_datetimes: Sequence[datetime],
    epex_values: Sequence[float | None],
    ref: dict[str, Any],
    *,
    warnings_out: list[str] | None = None,
) -> list[Any]:
    """Edibert ``PricePoint`` per input slot, in input order (naive slots = house time).

    Warnings are logged once per tariff; ``warnings_out`` also collects them (reports).
    """
    if len(slot_datetimes) != len(epex_values):
        raise ValueError("slot_datetimes und epex_values müssen gleich lang sein.")
    if not slot_datetimes:
        return []
    ctx = _context(ref)
    tariff = _tariff(ref, direction)
    grid_fee = _grid_fee(ref) if direction == eb.IMPORT else None
    utc_slots = [ctx.to_local(slot).astimezone(UTC) for slot in slot_datetimes]
    market = {
        slot: float(value)
        for slot, value in zip(utc_slots, epex_values)
        if value is not None
    }
    points: list[Any] = []
    for start, end in _runs(utc_slots):
        series = eb.price_series(
            tariff,
            ctx,
            utc_slots[start],
            utc_slots[end - 1] + _SLOT,
            market=market,
            grid_fee=grid_fee,
        )
        _log_warnings(tariff.id, series.warnings)
        if warnings_out is not None:
            warnings_out.extend(eb.warning_text(warning) for warning in series.warnings)
        points.extend(series.points)
    return points


def import_cents(
    slot_datetimes: Sequence[datetime],
    epex_values: Sequence[float | None],
    ref: dict[str, Any],
) -> list[float]:
    """``k_act`` per slot (cent/kWh incl. grid fee and VAT)."""
    return [point.cent for point in price_points(eb.IMPORT, slot_datetimes, epex_values, ref)]


def export_cents(
    slot_datetimes: Sequence[datetime],
    epex_values: Sequence[float | None],
    ref: dict[str, Any],
) -> list[float]:
    """``k_push_act`` per slot (cent/kWh)."""
    return [point.cent for point in price_points(eb.EXPORT, slot_datetimes, epex_values, ref)]
