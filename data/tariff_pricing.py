"""Bezugs- und Einspeisepreise aus Tarif-Specs (DACH-Prototyp, Backtesting)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

IMPORT_SPOT_TYPES = frozenset({"spot_hourly", "ex_post_spot", "monthly_market"})
EXPORT_SPOT_TYPES = frozenset({"spot_hourly", "ex_post_spot", "dynamic_epex"})
IMPORT_LEGACY_AWATTAR = "awattar"
IMPORT_FIXED = "fixed_cent"
IMPORT_MONTHLY = "monthly_table"
EXPORT_FIXED = "fixed"
EXPORT_MONTHLY = "monthly_table"
EXPORT_MONTHLY_FLOAT = "monthly_float"

MARKET_ZONE_BY_LAND = {
    "AT": "AT",
    "DE": "DE-LU",
    "CH": "CH",
}


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


def _legacy_awattar_brutto(epex_cent: float, awattar_cfg: dict[str, Any]) -> float:
    netzverlust = float(awattar_cfg["netzverlust_faktor"])
    fix_aufschlag = float(awattar_cfg["fix_aufschlag_cent"])
    mwst_faktor = float(awattar_cfg["mwst_austria_faktor"])
    return round((float(epex_cent) * netzverlust + fix_aufschlag) * mwst_faktor, 4)


def _awattar_import_cfg(tariff: dict[str, Any]) -> dict[str, Any]:
    keys = ("netzverlust_faktor", "fix_aufschlag_cent", "mwst_austria_faktor")
    if all(key in tariff for key in keys):
        return {key: float(tariff[key]) for key in keys}
    raise ValueError(
        "Tarif type 'awattar' erfordert fix_aufschlag_cent, netzverlust_faktor "
        "und mwst_austria_faktor im Tarif-Eintrag (tariffs.json)."
    )


def _awattar_export_cfg(tariff: dict[str, Any]) -> dict[str, Any]:
    if "feed_in_fee_factor" not in tariff:
        raise ValueError(
            "Tarif type 'dynamic_epex' erfordert feed_in_fee_factor im Tarif-Eintrag "
            "(tariffs.json)."
        )
    return {
        "feed_in_fee_factor": float(tariff["feed_in_fee_factor"]),
        "feed_in_fix_cent": float(tariff.get("feed_in_fix_cent", 0.0)),
    }


def _monthly_table_lookup(tariff: dict[str, Any]) -> dict[tuple[int, int], float]:
    rates = tariff.get("monthly_rates")
    if not isinstance(rates, list):
        raise ValueError("Tarif type 'monthly_table' erfordert monthly_rates.")
    return {
        (int(row["year"]), int(row["month"])): float(row["tariff_cent_kwh"])
        for row in rates
    }


def _spot_import_cent(
    epex_cent: float,
    tariff: dict[str, Any],
    *,
    netzentgelt_override: float | None,
) -> float:
    settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
    markup = float(tariff.get("markup_percent", 0.0) or 0.0)
    work_price = (float(epex_cent) * (1.0 + markup / 100.0)) + settlement
    if netzentgelt_override is not None:
        work_price += float(netzentgelt_override)
    else:
        netzentgelt = tariff.get("netzentgelt_cent_kwh")
        if netzentgelt is not None:
            work_price += float(netzentgelt)
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
    if tariff_type == IMPORT_LEGACY_AWATTAR:
        return _legacy_awattar_brutto(
            epex_cent,
            _awattar_import_cfg(tariff),
        )
    if tariff_type == IMPORT_MONTHLY:
        if slot_datetime is None:
            raise ValueError(
                "Import-Tarif type 'monthly_table' erfordert slot_datetime."
            )
        lookup = _monthly_table_lookup(tariff)
        key = (slot_datetime.year, slot_datetime.month)
        if key not in lookup:
            raise ValueError(f"Kein Monatseintrag für {key[0]}-{key[1]:02d} im Import-Tarif.")
        price = lookup[key]
        return round(
            _apply_vat(
                price,
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
        return round(
            _apply_vat(
                fixed,
                prices_include_vat=bool(tariff.get("prices_include_vat", True)),
                vat_percent=float(tariff.get("vat_percent", 0.0) or 0.0),
            ),
            4,
        )
    raise ValueError(f"Unbekannter Import-Tariftyp '{tariff_type}'.")


def _legacy_dynamic_export(
    epex_cent: float,
    legacy_awattar: dict[str, Any],
) -> float:
    fee_factor = float(legacy_awattar["feed_in_fee_factor"])
    fix_cent = float(legacy_awattar.get("feed_in_fix_cent", 0.0))
    epex = float(epex_cent)
    return round(epex - fee_factor * abs(epex) + fix_cent, 4)


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
    elif tariff_type in {EXPORT_MONTHLY, EXPORT_MONTHLY_FLOAT}:
        if monthly_lookup is None or slot_datetime is None:
            raise ValueError(
                f"Export-Tarif type '{tariff_type}' erfordert slot_datetime und monthly_lookup."
            )
        key = (slot_datetime.year, slot_datetime.month)
        if key not in monthly_lookup:
            raise ValueError(f"Kein Monatseintrag für {key[0]}-{key[1]:02d} im Export-Tarif.")
        price = monthly_lookup[key]
    elif tariff_type == "dynamic_epex":
        if epex_cent is None:
            raise ValueError("Export-Tarif type 'dynamic_epex' erfordert EPEX Cent/kWh.")
        return _legacy_dynamic_export(
            epex_cent,
            _awattar_export_cfg(tariff),
        )
    elif tariff_type in EXPORT_SPOT_TYPES - {"dynamic_epex"}:
        if epex_cent is None:
            raise ValueError(f"Export-Tarif type '{tariff_type}' erfordert EPEX Cent/kWh.")
        settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
        price = float(epex_cent) - settlement
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
