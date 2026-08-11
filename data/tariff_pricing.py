"""Bezugs- und Einspeisepreise aus Tarif-Specs (DACH-Prototyp, Backtesting)."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Any

IMPORT_SPOT_TYPES = frozenset({"spot_hourly", "ex_post_spot", "monthly_market"})
EXPORT_SPOT_TYPES = frozenset({"spot_hourly", "ex_post_spot"})
IMPORT_FIXED = "fixed_cent"
IMPORT_MONTHLY = "monthly_table"
EXPORT_FIXED = "fixed"
EXPORT_MONTHLY = "monthly_table"

MARKET_ZONE_BY_LAND = {
    "AT": "AT",
    "DE": "DE-LU",
    "CH": "CH",
}

FALLBACK_PRIOR_YEAR = "prior_year"
FALLBACK_PRIOR_MONTH = "prior_month"

logger = logging.getLogger(__name__)
# Log each (label, year, month) fallback once per process (matrix has many slots).
_logged_monthly_fallbacks: set[tuple[str, int, int]] = set()


def market_zone_for_land(land: str) -> str:
    code = str(land or "").strip().upper()
    if code not in MARKET_ZONE_BY_LAND:
        raise ValueError(
            f"Unbekanntes Tarif-Land '{land}'. Erlaubt: {', '.join(sorted(MARKET_ZONE_BY_LAND))}."
        )
    return MARKET_ZONE_BY_LAND[code]


def _apply_vat(
    price_cent: float,
    *,
    prices_include_vat: bool,
    vat_percent: float,
) -> float:
    if prices_include_vat:
        return float(price_cent)
    return float(price_cent) * (1.0 + float(vat_percent) / 100.0)


def _monthly_table_lookup(tariff: dict[str, Any]) -> dict[tuple[int, int], float]:
    """Build (year, month) → cent/kWh from catalog rows or normalized triples.

    Accepts:
    - list of ``{year, month, tariff_cent_kwh}`` (JSON / tests)
    - sequence of ``(year, month, cent)`` from ``validate_fixed_monthly_feed_in_rates``
    """
    rates = tariff.get("monthly_rates")
    if not isinstance(rates, (list, tuple)) or not rates:
        raise ValueError("Tarif type 'monthly_table' erfordert monthly_rates.")
    lookup: dict[tuple[int, int], float] = {}
    for index, row in enumerate(rates):
        if isinstance(row, dict):
            lookup[(int(row["year"]), int(row["month"]))] = float(
                row["tariff_cent_kwh"]
            )
            continue
        if isinstance(row, (tuple, list)) and len(row) >= 3:
            lookup[(int(row[0]), int(row[1]))] = float(row[2])
            continue
        raise ValueError(
            f"monthly_rates[{index}] muss Objekt oder (year, month, cent) sein."
        )
    return lookup


def previous_calendar_month(year: int, month: int) -> tuple[int, int]:
    if month <= 1:
        return year - 1, 12
    return year, month - 1


def next_calendar_month(year: int, month: int) -> tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def is_within_days_of_next_month(
    when: date | datetime,
    *,
    days: int = 2,
) -> bool:
    """True in the last ``days`` calendar days of ``when``'s month.

    Used to surface missing next-month ``monthly_table`` rates only when the
    ~48h planning horizon can reach into the next month (default: last 2 days).
    """
    if days < 1:
        raise ValueError("days must be >= 1.")
    day = when.day
    last_day = monthrange(when.year, when.month)[1]
    return day > last_day - days


def _available_months_suffix(lookup: dict[tuple[int, int], float]) -> str:
    if not lookup:
        return " (Lookup leer)"
    first_y, first_m = min(lookup)
    last_y, last_m = max(lookup)
    return (
        f" verfügbar: {first_y}-{first_m:02d} … {last_y}-{last_m:02d}"
        f" ({len(lookup)} Monate)"
    )


def lookup_monthly_cent(
    lookup: dict[tuple[int, int], float],
    year: int,
    month: int,
    *,
    label: str = "Tarif",
) -> tuple[float, str | None]:
    """Resolve Cent/kWh for (year, month) with temporary fallbacks.

    Order: exact → same month prior year → previous calendar month.
    Returns ``(cent, source)`` where ``source`` is None on exact match,
    else ``prior_year`` / ``prior_month``. Raises ValueError if none exist.
    """
    key = (int(year), int(month))
    if key in lookup:
        return float(lookup[key]), None

    prior_year_key = (key[0] - 1, key[1])
    if prior_year_key in lookup:
        cent = float(lookup[prior_year_key])
        _warn_monthly_fallback_once(
            label,
            key[0],
            key[1],
            prior_year_key[0],
            prior_year_key[1],
            kind="Vorjahr",
        )
        return cent, FALLBACK_PRIOR_YEAR

    prior_month_key = previous_calendar_month(key[0], key[1])
    if prior_month_key in lookup:
        cent = float(lookup[prior_month_key])
        _warn_monthly_fallback_once(
            label,
            key[0],
            key[1],
            prior_month_key[0],
            prior_month_key[1],
            kind="Vormonat",
        )
        return cent, FALLBACK_PRIOR_MONTH

    raise ValueError(
        f"Kein Monatseintrag für {key[0]}-{key[1]:02d} im {label}."
        f"{_available_months_suffix(lookup)}."
    )


def _warn_monthly_fallback_once(
    label: str,
    year: int,
    month: int,
    used_year: int,
    used_month: int,
    *,
    kind: str,
) -> None:
    token = (str(label), int(year), int(month))
    if token in _logged_monthly_fallbacks:
        return
    _logged_monthly_fallbacks.add(token)
    logger.warning(
        "Kein Monatseintrag für %04d-%02d im %s; temporär %04d-%02d "
        "(%s) verwendet — bitte tariffs.json aktualisieren "
        "(Szenarienkonfigurator).",
        year,
        month,
        label,
        used_year,
        used_month,
        kind,
    )


def monthly_rates_cover_month(tariff: dict[str, Any], year: int, month: int) -> bool:
    """True if tariff monthly_rates contain an exact (year, month) row."""
    if str(tariff.get("type", "")).strip().lower() != IMPORT_MONTHLY:
        return True
    rates = tariff.get("monthly_rates")
    if not isinstance(rates, (list, tuple)) or not rates:
        return False
    try:
        lookup = _monthly_table_lookup(tariff)
    except ValueError:
        return False
    return (int(year), int(month)) in lookup


def missing_next_month_tariff_hints(
    *,
    import_tariff: dict[str, Any] | None,
    export_tariff: dict[str, Any] | None,
    year: int,
    month: int,
) -> list[str]:
    """German captions for monthly_table tariffs missing exact (year, month)."""
    hints: list[str] = []
    for side_label, tariff in (
        ("Bezug", import_tariff),
        ("Einspeise", export_tariff),
    ):
        if not isinstance(tariff, dict):
            continue
        if monthly_rates_cover_month(tariff, year, month):
            continue
        name = str(tariff.get("label") or tariff.get("id") or side_label)
        hints.append(f"{side_label}: {name}")
    return hints


def _add_netzentgelt(
    work_price: float,
    *,
    netzentgelt_override: float | None,
) -> float:
    """Add volumetric Netznutzung Arbeitspreis (Cent/kWh) from house-profile settings."""
    if netzentgelt_override is None:
        return float(work_price)
    return float(work_price) + float(netzentgelt_override)


def _spot_import_cent(
    epex_cent: float,
    tariff: dict[str, Any],
    *,
    netzentgelt_override: float | None,
) -> float:
    settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
    markup = float(tariff.get("markup_percent", 0.0) or 0.0)
    work_price = (float(epex_cent) * (1.0 + markup / 100.0)) + settlement
    work_price = _add_netzentgelt(work_price, netzentgelt_override=netzentgelt_override)
    return _apply_vat(
        work_price,
        prices_include_vat=bool(tariff.get("prices_include_vat", True)),
        vat_percent=float(tariff.get("vat_percent", 0.0) or 0.0),
    )


def import_cent_kwh(
    epex_cent: float,
    tariff: dict[str, Any],
    *,
    netzentgelt_override: float | None = None,
    slot_datetime: datetime | None = None,
) -> float:
    """EPEX Cent/kWh → Bezugspreis Cent/kWh laut Tarif-Spec."""
    tariff_type = str(tariff.get("type", "")).strip().lower()
    if tariff_type == IMPORT_MONTHLY:
        if slot_datetime is None:
            raise ValueError(
                "Import-Tarif type 'monthly_table' erfordert slot_datetime."
            )
        lookup = _monthly_table_lookup(tariff)
        price, _source = lookup_monthly_cent(
            lookup,
            slot_datetime.year,
            slot_datetime.month,
            label="Import-Tarif",
        )
        work = _add_netzentgelt(price, netzentgelt_override=netzentgelt_override)
        return round(
            _apply_vat(
                work,
                prices_include_vat=bool(tariff.get("prices_include_vat", True)),
                vat_percent=float(tariff.get("vat_percent", 0.0) or 0.0),
            ),
            4,
        )
    if tariff_type in IMPORT_SPOT_TYPES:
        return round(
            _spot_import_cent(
                epex_cent,
                tariff,
                netzentgelt_override=netzentgelt_override,
            ),
            4,
        )
    if tariff_type == IMPORT_FIXED:
        if "fix_cent_kwh" not in tariff:
            raise ValueError("Import-Tarif type 'fixed_cent' erfordert fix_cent_kwh.")
        fixed = float(tariff["fix_cent_kwh"])
        work = _add_netzentgelt(fixed, netzentgelt_override=netzentgelt_override)
        return round(
            _apply_vat(
                work,
                prices_include_vat=bool(tariff.get("prices_include_vat", True)),
                vat_percent=float(tariff.get("vat_percent", 0.0) or 0.0),
            ),
            4,
        )
    raise ValueError(f"Unbekannter Import-Tariftyp '{tariff_type}'.")


def _spot_export_cent(epex_cent: float, tariff: dict[str, Any]) -> float:
    """EPEX − fee_factor×|EPEX| − settlement + fix_cent (before VAT)."""
    fee_factor = float(tariff.get("feed_in_fee_factor", 0.0) or 0.0)
    if fee_factor < 0.0:
        raise ValueError("feed_in_fee_factor muss >= 0 sein.")
    settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
    fix_cent = float(tariff.get("feed_in_fix_cent", 0.0) or 0.0)
    epex = float(epex_cent)
    return epex - fee_factor * abs(epex) - settlement + fix_cent


def export_cent_kwh(
    epex_cent: float | None,
    tariff: dict[str, Any],
    *,
    slot_datetime: datetime | None = None,
    monthly_lookup: dict[tuple[int, int], float] | None = None,
) -> float:
    """EPEX Cent/kWh → Einspeisevergütung Cent/kWh laut Tarif-Spec."""
    tariff_type = str(tariff.get("type", "")).strip().lower()
    if tariff_type == EXPORT_FIXED:
        if "k_push_cent" not in tariff:
            raise ValueError("Export-Tarif type 'fixed' erfordert k_push_cent.")
        price = float(tariff["k_push_cent"])
    elif tariff_type == EXPORT_MONTHLY:
        if monthly_lookup is None or slot_datetime is None:
            raise ValueError(
                f"Export-Tarif type '{tariff_type}' erfordert slot_datetime und monthly_lookup."
            )
        price, _source = lookup_monthly_cent(
            monthly_lookup,
            slot_datetime.year,
            slot_datetime.month,
            label="Export-Tarif",
        )
    elif tariff_type in EXPORT_SPOT_TYPES:
        if epex_cent is None:
            raise ValueError(f"Export-Tarif type '{tariff_type}' erfordert EPEX Cent/kWh.")
        price = _spot_export_cent(epex_cent, tariff)
    else:
        raise ValueError(f"Unbekannter Export-Tariftyp '{tariff_type}'.")

    return round(
        _apply_vat(
            price,
            prices_include_vat=bool(tariff.get("prices_include_vat", True)),
            vat_percent=float(tariff.get("vat_percent", 0.0) or 0.0),
        ),
        4,
    )
