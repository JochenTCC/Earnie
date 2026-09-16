"""Battery η and standby metrics for Analyse Verbrauch & Kosten."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ui.consumer_cost_analysis_data import SLOT_DURATION_HOURS, PeriodTotals


def measured_battery_efficiency(
    charge_kwh: float, discharge_kwh: float
) -> float | None:
    """η = sqrt(E_discharge / E_charge); None if either energy is not positive."""
    charge = float(charge_kwh)
    discharge = float(discharge_kwh)
    if charge <= 0.0 or discharge <= 0.0:
        return None
    return math.sqrt(discharge / charge)


def configured_standby_kwh(standby_power_kw: float, slot_count: int) -> float:
    """HK standby energy for the window: standby_power_kw × hours."""
    power = max(0.0, float(standby_power_kw or 0.0))
    slots = max(0, int(slot_count))
    return round(power * slots * SLOT_DURATION_HOURS, 4)


def residual_standby_kwh(
    charge_kwh: float,
    discharge_kwh: float,
    eta_nominal: float,
) -> float:
    """Standby residual B after peeling roundtrip with nominal η.

    B = max(0, E_charge × η_nom² − E_discharge). Invalid η → no peel (η² = 0).
    """
    charge = float(charge_kwh)
    discharge = float(discharge_kwh)
    eta = float(eta_nominal)
    eta_sq = eta * eta if eta > 0.0 else 0.0
    return round(max(0.0, charge * eta_sq - discharge), 4)


def standby_diff_significant(
    a_kwh: float,
    b_kwh: float,
    *,
    threshold: float = 0.20,
) -> bool:
    """True when relative |A−B|/max(A,B) exceeds threshold (both sides matter)."""
    a = float(a_kwh)
    b = float(b_kwh)
    peak = max(a, b, 0.0)
    if peak <= 1e-12:
        return False
    return abs(a - b) / peak > float(threshold)


def recommended_standby_power_kw(standby_b_kwh: float, slot_count: int) -> float | None:
    """Implied HK standby_power_kw from residual B ÷ window hours."""
    slots = max(0, int(slot_count))
    hours = slots * SLOT_DURATION_HOURS
    if hours <= 1e-12:
        return None
    return round(max(0.0, float(standby_b_kwh)) / hours, 4)


@dataclass(frozen=True)
class BatteryPeriodMetrics:
    """Measured η plus configured (A) and residual (B) standby for a window."""

    eta_measured: float | None
    eta_nominal: float
    standby_a_kwh: float
    standby_b_kwh: float
    standby_nominal_kw: float
    recommended_standby_kw: float | None
    standby_hint: bool


def build_battery_period_metrics(
    totals: PeriodTotals,
    *,
    eta_nominal: float,
    standby_power_kw: float,
) -> BatteryPeriodMetrics:
    """Derive chart/caption metrics from period totals and live HK params."""
    charge = float(totals.battery_charge_kwh)
    discharge = float(totals.battery_discharge_kwh)
    eta_nom = float(eta_nominal)
    standby_kw = max(0.0, float(standby_power_kw or 0.0))
    standby_a = configured_standby_kwh(standby_kw, totals.slot_count)
    standby_b = residual_standby_kwh(charge, discharge, eta_nom)
    return BatteryPeriodMetrics(
        eta_measured=measured_battery_efficiency(charge, discharge),
        eta_nominal=eta_nom,
        standby_a_kwh=standby_a,
        standby_b_kwh=standby_b,
        standby_nominal_kw=standby_kw,
        recommended_standby_kw=recommended_standby_power_kw(
            standby_b, totals.slot_count
        ),
        standby_hint=standby_diff_significant(standby_a, standby_b),
    )
