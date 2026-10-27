"""Einspeisevergütung je Slot (``k_push_act``) aus dem Einspeisetarif — bepreist von Edibert.

Seit Edibert P3b gibt es keinen eigenen Einspeise-Pfad mehr (kein ``feed_in_mode``, keine
Monatstabelle, kein fixes ``k_push_cent`` ohne Tarif): jede Zeile bekommt den Preis des
Einspeisetarifs aus der Edibert-Preisreferenz. Ein Szenario ohne Einspeisetarif kann nicht
bepreist werden (Fehler, kein Ersatzwert).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from data.edibert_slot_prices import MarketFor


@dataclass(frozen=True)
class FeedInSettings:
    # Constant of a fixed export tariff (0 for other types); only history / log fallbacks.
    k_push_cent: float
    # Edibert pricing reference (``_edibert_pricing``) of the resolved scenario.
    edibert_pricing: dict | None = None


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


def feed_in_settings_from_dict(runtime: dict[str, Any]) -> FeedInSettings:
    if "k_push_cent" not in runtime:
        raise KeyError("feed_in_settings erfordert k_push_cent aus aufgelöstem Export-Tarif.")
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY

    return FeedInSettings(
        k_push_cent=float(runtime["k_push_cent"]),
        edibert_pricing=runtime.get(EDIBERT_PRICING_KEY),
    )


def export_cents_for_slots(
    slot_datetimes: list[datetime | None],
    epex_values: list[float | None],
    settings: FeedInSettings,
    *,
    market_for: MarketFor | None = None,
) -> list[float]:
    """``k_push_act`` per slot from the export tariff (a whole list, so hourly means work)."""
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, export_cents, require_pricing_reference

    if any(slot is None for slot in slot_datetimes):
        raise ValueError("Einspeisepreis erfordert slot_datetime je Zeile.")
    ref = require_pricing_reference(
        {EDIBERT_PRICING_KEY: settings.edibert_pricing}, where="Einspeisepreis"
    )
    return export_cents(slot_datetimes, epex_values, ref, market_for=market_for)  # type: ignore[arg-type]


def enrich_matrix_feed_in_prices(
    matrix: list[dict[str, Any]],
    settings: FeedInSettings,
    *,
    market_for: MarketFor | None = None,
) -> None:
    """Setzt k_push_act je Matrix-Zeile (in-place)."""
    prices = export_cents_for_slots(
        [row.get("slot_datetime") for row in matrix],
        [row.get("price_buy") for row in matrix],
        settings,
        market_for=market_for,
    )
    for row, price in zip(matrix, prices):
        row["k_push_act"] = price


def k_push_act_for_matrix_row(row: dict[str, Any], fallback_k_push: float) -> float:
    """Liest k_push_act aus der Matrix-Zeile oder nutzt den Fallback."""
    value = row.get("k_push_act")
    if value is not None:
        return float(value)
    return float(fallback_k_push)
