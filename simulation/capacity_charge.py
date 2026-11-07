"""Capacity charge (Leistungspreis) of Scenario Explorer results, post-aggregation only.

The charge bills the highest quarter hour of each calendar month, so it differs per month and per
result. It never enters ``sim_cost``: like the fixed fees it is added to the summary and the invoice.
Prices, minimum and start date come from the grid area through Edibert.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from simulation.booked_consumption import _unique_slots

CAPACITY_KEY = "capacity_by_scenario"


@dataclass(frozen=True)
class CapacityMonth:
    """One calendar month: booked peak, billed power and the amount."""

    month: str  # YYYY-MM
    charge_id: str
    peak_kw: float
    peak_slot: str
    billed_kw: float
    net_eur: float
    gross_eur: float  # with the import tariff's VAT, as the fixed grid amounts


@dataclass(frozen=True)
class CapacityResult:
    """Capacity charge of one result; empty when the grid area has none in the period."""

    months: tuple[CapacityMonth, ...] = ()
    skipped: dict[str, str] = field(default_factory=dict)  # entry ID → status not included
    not_convex: tuple[str, ...] = ()  # entry IDs whose band rate falls

    @property
    def gross_eur(self) -> float:
        return sum(month.gross_eur for month in self.months)

    @property
    def gross_by_month(self) -> dict[str, float]:
        return {month.month: month.gross_eur for month in self.months}

    def as_dict(self) -> dict:
        return {
            "months": [asdict(month) for month in self.months],
            "skipped": dict(self.skipped),
            "not_convex": list(self.not_convex),
            "gross_eur": self.gross_eur,
        }


def _pricing_reference(params: dict | None) -> dict | None:
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY

    ref = params.get(EDIBERT_PRICING_KEY) if isinstance(params, dict) else None
    return ref if isinstance(ref, dict) else None


def _month_peaks(df: pd.DataFrame) -> dict[str, tuple[float, pd.Timestamp]]:
    """Highest booked import power per calendar month; every slot counts once (last booking wins)."""
    if "import_kwh" not in df.columns:
        raise ValueError("Leistungspreis: Ergebnisreihe ohne Spalte import_kwh.")
    unique, _duplicates = _unique_slots(df)
    power_kw = unique["import_kwh"].fillna(0.0).clip(lower=0.0) / validate_dt_h(DEFAULT_DT_H)
    peaks: dict[str, tuple[float, pd.Timestamp]] = {}
    for month, part in power_kw.groupby(power_kw.index.strftime("%Y-%m")):
        slot = part.idxmax()
        peaks[str(month)] = (float(part.loc[slot]), slot)
    return peaks


def capacity_for_result(df: pd.DataFrame, params: dict | None) -> CapacityResult:
    """Capacity charge per calendar month touched by ``df``; a partial month counts in full."""
    from data.edibert_slot_prices import grid_fee, tariff
    from house_config.edibert_tariffs import (
        IMPORT,
        capacity_charge_for_month,
        capacity_charge_net_eur,
    )

    ref = _pricing_reference(params)
    fee = grid_fee(ref) if ref is not None else None
    if fee is None or not (fee.capacity or fee.capacity_skipped):
        return CapacityResult()
    months: list[CapacityMonth] = []
    used: dict[str, object] = {}
    if fee.capacity and not df.empty:
        factor = 1.0 + float(tariff(ref, IMPORT).vat_percent) / 100.0
        for month, (peak_kw, slot) in sorted(_month_peaks(df).items()):
            charge = capacity_charge_for_month(fee, date.fromisoformat(f"{month}-01"))
            if charge is None:
                continue
            net = capacity_charge_net_eur(charge, peak_kw)
            used[charge.id] = charge
            months.append(
                CapacityMonth(
                    month=month,
                    charge_id=charge.id,
                    peak_kw=peak_kw,
                    peak_slot=slot.isoformat(),
                    billed_kw=max(peak_kw, float(charge.min_kw)),
                    net_eur=net,
                    gross_eur=net * factor,
                )
            )
    return CapacityResult(
        months=tuple(months),
        skipped=dict(fee.capacity_skipped),
        not_convex=tuple(cid for cid, charge in used.items() if not charge.convex),
    )


def capacity_by_result(
    results: dict[str, pd.DataFrame],
    params_by_result: dict[str, dict | None],
) -> dict[str, CapacityResult]:
    """Results that have a capacity charge or a skipped entry; the others are left out."""
    out: dict[str, CapacityResult] = {}
    for result_id, df in results.items():
        if df is None or df.empty:
            continue
        capacity = capacity_for_result(df, params_by_result.get(result_id))
        if capacity.months or capacity.skipped:
            out[result_id] = capacity
    return out


def check_capacity_coverage(params: dict | None, start: pd.Timestamp, end: pd.Timestamp) -> None:
    """Fail before a long run when the grid area has a gap in the period (``CAPACITY_CHARGE_MISSING``)."""
    from data.edibert_slot_prices import grid_fee
    from house_config.edibert_tariffs import capacity_charge_for_month

    ref = _pricing_reference(params)
    fee = grid_fee(ref) if ref is not None else None
    if fee is None or not fee.capacity:
        return
    for period in pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M"):
        capacity_charge_for_month(fee, period.start_time.date())
