"""Einspeisevergütung: fix (k_push_cent) oder stündlich dynamisch (EPEX / Awattar Sunny Spot)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

FEED_IN_MODE_FIXED = "fixed"
FEED_IN_MODE_DYNAMIC_EPEX = "dynamic_epex"
VALID_FEED_IN_MODES = frozenset({FEED_IN_MODE_FIXED, FEED_IN_MODE_DYNAMIC_EPEX})


@dataclass(frozen=True)
class FeedInSettings:
    mode: str
    k_push_cent: float
    fee_factor: float
    fix_cent: float
    monthly_fixed_tariffs: tuple[tuple[int, int, float], ...] | None = None
    export_tariff_spec: dict | None = None
    # Edibert pricing reference (``_edibert_pricing``); only set with EARNIE_PRICING_ENGINE=edibert.
    edibert_pricing: dict | None = None


def validate_feed_in_mode(mode: str) -> str:
    normalized = str(mode).strip().lower()
    if normalized not in VALID_FEED_IN_MODES:
        raise ValueError(
            f"Unbekannter feed_in_mode '{mode}'. "
            f"Erlaubt: {', '.join(sorted(VALID_FEED_IN_MODES))}."
        )
    return normalized


def validate_fixed_monthly_feed_in_rates(raw: list) -> tuple[tuple[int, int, float], ...]:
    """Validiert Monatstarife (year/month/tariff_cent_kwh), z. B. monthly_table oder OeMAG."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "monthly_rates muss ein nicht-leeres Array sein."
        )
    seen: set[tuple[int, int]] = set()
    entries: list[tuple[int, int, float]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"monthly_rates[{index}] muss ein Objekt sein."
            )
        for key in ("year", "month", "tariff_cent_kwh"):
            if key not in item:
                raise ValueError(
                    f"monthly_rates[{index}]: '{key}' fehlt."
                )
        year = int(item["year"])
        month = int(item["month"])
        tariff = float(item["tariff_cent_kwh"])
        if month < 1 or month > 12:
            raise ValueError(
                f"monthly_rates[{index}]: month muss 1–12 sein."
            )
        if tariff <= 0.0:
            raise ValueError(
                f"monthly_rates[{index}]: tariff_cent_kwh muss > 0 sein."
            )
        key = (year, month)
        if key in seen:
            raise ValueError(
                f"monthly_rates: doppelter Eintrag für {year}-{month:02d}."
            )
        seen.add(key)
        entries.append((year, month, tariff))
    return tuple(entries)


def monthly_fixed_tariff_lookup(
    tariffs: tuple[tuple[int, int, float], ...],
) -> dict[tuple[int, int], float]:
    return {(year, month): tariff for year, month, tariff in tariffs}


def _fixed_tariff_for_slot(
    slot_datetime: datetime | None,
    settings: FeedInSettings,
) -> float:
    from data.tariff_pricing import lookup_monthly_cent

    tariffs = settings.monthly_fixed_tariffs
    if tariffs is None:
        return float(settings.k_push_cent)
    if slot_datetime is None:
        raise ValueError(
            "feed_in_mode 'fixed' mit Monatstariftabelle erfordert "
            "slot_datetime pro Matrix-Zeile bzw. Stunde."
        )
    lookup = monthly_fixed_tariff_lookup(tariffs)
    price, _source = lookup_monthly_cent(
        lookup,
        slot_datetime.year,
        slot_datetime.month,
        label="Einspeisetarif (monthly_rates)",
    )
    return price


def epex_to_feed_in_cent(
    epex_cent: float,
    fee_factor: float,
    fix_cent: float,
) -> float:
    """
    EPEX Cent/kWh → Einspeisevergütung (Awattar SUNNY Spot 60 min, netto):
    EPEX − fee_factor × |EPEX| + fix_cent (z. B. regionale Netz-/Abgaben-Offset).
    """
    epex = float(epex_cent)
    fee = float(fee_factor)
    fix = float(fix_cent)
    if fee < 0:
        raise ValueError("feed_in_fee_factor muss >= 0 sein.")
    return round(epex - fee * abs(epex) + fix, 4)


def resolve_k_push_act(
    epex_cent: float | None,
    settings: FeedInSettings,
    *,
    slot_datetime: datetime | None = None,
) -> float:
    from settings.pricing_engine import uses_edibert_pricing

    # Without an export tariff there is nothing to price: the constant k_push_cent stays.
    if uses_edibert_pricing() and settings.export_tariff_spec is not None:
        return _edibert_k_push([slot_datetime], [epex_cent], settings)[0]
    if settings.export_tariff_spec is not None:
        from data.tariff_pricing import export_cent_kwh

        monthly_lookup = None
        if settings.monthly_fixed_tariffs is not None:
            monthly_lookup = monthly_fixed_tariff_lookup(settings.monthly_fixed_tariffs)
        return export_cent_kwh(
            epex_cent,
            settings.export_tariff_spec,
            slot_datetime=slot_datetime,
            monthly_lookup=monthly_lookup,
        )

    mode = validate_feed_in_mode(settings.mode)
    if mode == FEED_IN_MODE_FIXED:
        return _fixed_tariff_for_slot(slot_datetime, settings)
    if epex_cent is None:
        raise ValueError(
            "feed_in_mode 'dynamic_epex' erfordert price_buy (EPEX Cent/kWh) pro Matrix-Zeile."
        )
    return epex_to_feed_in_cent(epex_cent, settings.fee_factor, settings.fix_cent)


def _edibert_k_push(
    slot_datetimes: list[datetime | None],
    epex_values: list[float | None],
    settings: FeedInSettings,
) -> list[float]:
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, export_cents, require_pricing_reference

    if any(slot is None for slot in slot_datetimes):
        raise ValueError("EARNIE_PRICING_ENGINE=edibert: Einspeisepreis erfordert slot_datetime.")
    ref = require_pricing_reference(
        {EDIBERT_PRICING_KEY: settings.edibert_pricing}, where="Einspeisepreis"
    )
    return export_cents(slot_datetimes, epex_values, ref)  # type: ignore[arg-type]


def _export_fee_fields(export_spec: dict | None) -> tuple[float, float]:
    if export_spec is None:
        return 0.0, 0.0
    export_type = str(export_spec.get("type", "")).strip().lower()
    if export_type not in {"spot_hourly", "ex_post_spot"}:
        return 0.0, 0.0
    return (
        float(export_spec.get("feed_in_fee_factor", 0.0) or 0.0),
        float(export_spec.get("feed_in_fix_cent", 0.0) or 0.0),
    )


def feed_in_settings_from_dict(
    runtime: dict[str, Any],
    *,
    monthly_fixed_tariffs: tuple[tuple[int, int, float], ...] | None = None,
    export_tariff_spec: dict | None = None,
) -> FeedInSettings:
    if "k_push_cent" not in runtime:
        raise KeyError("feed_in_settings erfordert k_push_cent aus aufgelöstem Export-Tarif.")
    mode = validate_feed_in_mode(runtime.get("feed_in_mode", FEED_IN_MODE_FIXED))
    k_push = float(runtime["k_push_cent"])
    spec = export_tariff_spec
    if spec is None and runtime.get("_export_tariff_spec") is not None:
        spec = dict(runtime["_export_tariff_spec"])
    fee_factor, fix_cent = _export_fee_fields(spec)
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY

    return FeedInSettings(
        mode=mode,
        k_push_cent=k_push,
        fee_factor=fee_factor,
        fix_cent=fix_cent,
        monthly_fixed_tariffs=monthly_fixed_tariffs,
        export_tariff_spec=spec,
        edibert_pricing=runtime.get(EDIBERT_PRICING_KEY),
    )


def enrich_matrix_feed_in_prices(matrix: list[dict[str, Any]], settings: FeedInSettings) -> None:
    """Setzt k_push_act je Matrix-Zeile (in-place)."""
    from data.tariff_pricing import SETTLEMENT_MTU_HOURLY, tariff_settlement_mtu
    from settings.pricing_engine import uses_edibert_pricing

    if uses_edibert_pricing() and settings.export_tariff_spec is not None:
        prices = _edibert_k_push(
            [row.get("slot_datetime") for row in matrix],
            [row.get("price_buy") for row in matrix],
            settings,
        )
        for row, price in zip(matrix, prices):
            row["k_push_act"] = price
        return

    epex_for_export = [row.get("price_buy") for row in matrix]
    if tariff_settlement_mtu(settings.export_tariff_spec) == SETTLEMENT_MTU_HOURLY:
        slots = [row.get("slot_datetime") for row in matrix]
        if all(slot is not None for slot in slots):
            from data.market_prices import hourly_settlement_epex_values

            epex_for_export = hourly_settlement_epex_values(epex_for_export, slots)
    for row, epex in zip(matrix, epex_for_export):
        row["k_push_act"] = resolve_k_push_act(
            epex,
            settings,
            slot_datetime=row.get("slot_datetime"),
        )


def k_push_act_for_matrix_row(row: dict[str, Any], fallback_k_push: float) -> float:
    """Liest k_push_act aus der Matrix-Zeile oder nutzt den Fallback."""
    value = row.get("k_push_act")
    if value is not None:
        return float(value)
    return float(fallback_k_push)
