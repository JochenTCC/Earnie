"""OeMAG-Referenzkurve und Skalierung für monthly_float Export-Tarife."""
from __future__ import annotations

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates

REQUIRED_OEMAG_MONTHS = 12


def load_oemag_monthly_reference_rates(
    backtesting_scenarios_doc: dict,
) -> tuple[tuple[int, int, float], ...]:
    """Lädt und validiert die 12-monatige OeMAG-Referenzkurve."""
    raw = backtesting_scenarios_doc.get("oemag_monthly_feed_in_rates")
    if raw is None:
        raise ValueError(
            "oemag_monthly_feed_in_rates fehlt in backtesting_scenarios.json "
            "(erforderlich für monthly_float Export-Tarife)."
        )
    rates = validate_fixed_monthly_feed_in_rates(raw)
    if len(rates) != REQUIRED_OEMAG_MONTHS:
        raise ValueError(
            f"oemag_monthly_feed_in_rates muss genau {REQUIRED_OEMAG_MONTHS} Einträge "
            f"haben, nicht {len(rates)}."
        )
    return rates


def load_monthly_float_reference_cent(backtesting_scenarios_doc: dict) -> float:
    raw = backtesting_scenarios_doc.get("monthly_float_reference_cent_kwh")
    if raw is None:
        raise ValueError(
            "monthly_float_reference_cent_kwh fehlt in backtesting_scenarios.json "
            "(erforderlich für monthly_float Export-Tarife)."
        )
    reference = float(raw)
    if reference <= 0.0:
        raise ValueError("monthly_float_reference_cent_kwh muss > 0 sein.")
    return reference


def build_monthly_float_lookup(
    oemag_rates: tuple[tuple[int, int, float], ...],
    reference_cent_kwh: float,
    tariff: dict,
) -> tuple[tuple[int, int, float], ...]:
    """
    Skaliert OeMAG-Monatspreise proportional zu arbeitspreis_kwh_cent.
    Abzug: settlement_fee_cent_kwh (min. 0 ct/kWh).
    """
    if "arbeitspreis_kwh_cent" not in tariff:
        raise ValueError("Export-Tarif type 'monthly_float' erfordert arbeitspreis_kwh_cent.")
    work_price = float(tariff["arbeitspreis_kwh_cent"])
    if work_price <= 0.0:
        raise ValueError("arbeitspreis_kwh_cent muss > 0 sein.")
    reference = float(reference_cent_kwh)
    if reference <= 0.0:
        raise ValueError("monthly_float_reference_cent_kwh muss > 0 sein.")
    settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
    factor = work_price / reference
    scaled: list[tuple[int, int, float]] = []
    for year, month, oemag_cent in oemag_rates:
        cent = max(0.0, oemag_cent * factor - settlement)
        scaled.append((year, month, round(cent, 4)))
    return tuple(scaled)
