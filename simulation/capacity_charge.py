"""Capacity charge (Leistungspreis) of Scenario Explorer results, post-aggregation only.

The charge bills the highest quarter hour of each calendar month, so it differs per month and per
result. It never enters ``sim_cost``: like the fixed fees it is added to the summary and the invoice.
Prices, minimum and start date come from the grid area through Edibert.

For a result planned with a cap, each booked slot over the cap gets a cause (P6c): the plan's own
(``optimizer.import_cap_report``) when the plan went over its limit there, ``not_planned`` for a
trivial window or Automatik, else one of the two SE causes below.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

from optimizer.import_cap_report import CAUSE_LABELS_DE, SLOT_CAUSE_KEY, SLOT_LIMIT_KEY
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from simulation.booked_consumption import _unique_slots

CAPACITY_KEY = "capacity_by_scenario"
_OVER_CAP_TOLERANCE_KW = 1e-6

# The plan held its limit, but an earlier peak of the month had lifted that limit above the cap.
CAUSE_MONTH_PEAK = "month_peak"
# The plan held its limit, the booked slot did not (forecast mode, or the control mapping).
CAUSE_BOOKED_ABOVE_PLAN = "booked_above_plan"

SE_CAUSE_LABELS_DE = {
    **CAUSE_LABELS_DE,
    CAUSE_MONTH_PEAK: "Monatsspitze schon höher, Grenze angehoben",
    CAUSE_BOOKED_ABOVE_PLAN: "Gebucht über dem Plan",
}


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
    # Only for a result planned with a cap. The booked rows can differ from the plan.
    import_cap_kw: float | None = None
    slots_over_cap: int = 0
    days_over_cap: int = 0
    causes_over_cap: dict[str, int] = field(default_factory=dict)  # main cause → booked slots


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


def _booked_import_kw(unique: pd.DataFrame) -> pd.Series:
    """Booked import power per slot of rows that hold every slot once."""
    if "import_kwh" not in unique.columns:
        raise ValueError("Leistungspreis: Ergebnisreihe ohne Spalte import_kwh.")
    return unique["import_kwh"].fillna(0.0).clip(lower=0.0) / validate_dt_h(DEFAULT_DT_H)


def _month_peaks(power_kw: pd.Series) -> dict[str, tuple[float, pd.Timestamp]]:
    """Highest booked import power per calendar month."""
    peaks: dict[str, tuple[float, pd.Timestamp]] = {}
    for month, part in power_kw.groupby(power_kw.index.strftime("%Y-%m")):
        slot = part.idxmax()
        peaks[str(month)] = (float(part.loc[slot]), slot)
    return peaks


@dataclass(frozen=True)
class _OverCap:
    slots: int = 0
    days: int = 0
    causes: dict[str, int] = field(default_factory=dict)


def _slot_cause(power_kw: float, limit_kw: float, plan_cause: object) -> str:
    if isinstance(plan_cause, str) and plan_cause:
        return plan_cause
    if power_kw <= limit_kw + _OVER_CAP_TOLERANCE_KW:
        return CAUSE_MONTH_PEAK
    return CAUSE_BOOKED_ABOVE_PLAN


def _over_cap(unique: pd.DataFrame, power_kw: pd.Series, month: str, cap_kw: float | None) -> _OverCap:
    """Booked slots over the cap in ``month``: count, days touched and main causes."""
    if cap_kw is None:
        return _OverCap()
    in_month = power_kw.index.strftime("%Y-%m") == month
    over = power_kw[in_month & (power_kw > cap_kw + _OVER_CAP_TOLERANCE_KW).to_numpy()]
    if over.empty:
        return _OverCap()
    missing = [col for col in (SLOT_LIMIT_KEY, SLOT_CAUSE_KEY) if col not in unique.columns]
    if missing:
        raise ValueError(
            f"Bezugsgrenze: Ergebnisreihe ohne Spalte {', '.join(missing)}, "
            "obwohl mit Grenze geplant wurde."
        )
    causes: dict[str, int] = {}
    for slot, kw in over.items():
        limit = unique.at[slot, SLOT_LIMIT_KEY]
        if pd.isna(limit):
            raise ValueError(f"Bezugsgrenze: gebuchter Slot {slot} über der Grenze ohne Plan-Grenze.")
        cause = _slot_cause(float(kw), float(limit), unique.at[slot, SLOT_CAUSE_KEY])
        causes[cause] = causes.get(cause, 0) + 1
    return _OverCap(
        slots=len(over),
        days=int(over.index.normalize().nunique()),
        causes=dict(sorted(causes.items(), key=lambda item: (-item[1], item[0]))),
    )


def capacity_for_result(
    df: pd.DataFrame,
    params: dict | None,
    *,
    planned_cap_kw: float | None = None,
) -> CapacityResult:
    """Capacity charge per calendar month touched by ``df``; a partial month counts in full.

    ``planned_cap_kw``: the cap this result was planned with. L0 to L2 carry the scenario's params
    but plan without it, so the params alone cannot tell.
    """
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
        unique, _duplicates = _unique_slots(df)
        power_kw = _booked_import_kw(unique)
        for month, (peak_kw, slot) in sorted(_month_peaks(power_kw).items()):
            charge = capacity_charge_for_month(fee, date.fromisoformat(f"{month}-01"))
            if charge is None:
                continue
            net = capacity_charge_net_eur(charge, peak_kw)
            used[charge.id] = charge
            over = _over_cap(unique, power_kw, month, planned_cap_kw)
            months.append(
                CapacityMonth(
                    month=month,
                    charge_id=charge.id,
                    peak_kw=peak_kw,
                    peak_slot=slot.isoformat(),
                    billed_kw=max(peak_kw, float(charge.min_kw)),
                    net_eur=net,
                    gross_eur=net * factor,
                    import_cap_kw=planned_cap_kw,
                    slots_over_cap=over.slots,
                    days_over_cap=over.days,
                    causes_over_cap=over.causes,
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
    planned_cap_kw_by_result: Mapping[str, float] | None = None,
) -> dict[str, CapacityResult]:
    """Results that have a capacity charge or a skipped entry; the others are left out."""
    planned = planned_cap_kw_by_result or {}
    out: dict[str, CapacityResult] = {}
    for result_id, df in results.items():
        if df is None or df.empty:
            continue
        capacity = capacity_for_result(
            df, params_by_result.get(result_id), planned_cap_kw=planned.get(result_id)
        )
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
