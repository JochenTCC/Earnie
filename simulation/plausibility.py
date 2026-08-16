"""Window consumption plausibility checks for backtesting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from optimizer import _delivered_flex_kwh_from_rows
from simulation.baseload_validation import (
    baseload_kwh_from_chart_rows,
    derive_historical_baseload_kwh,
)

# Plausibilisierung: optimierter 24h-Verbrauch vs. historischer Gesamtverbrauch
# (MILP min_on-Constraints können kleine Abweichungen erzeugen)
CONSUMPTION_TOLERANCE_KWH = 0.5
CONSUMPTION_TOLERANCE_REL = 0.05


@dataclass
class PlausibilityResult:
    window_end: datetime
    historical_kwh: float
    optimized_kwh: float
    diff_kwh: float
    ok: bool
    historical_baseload_kwh: float | None = None
    optimized_baseload_kwh: float | None = None
    historical_flex_kwh: float | None = None
    optimized_flex_kwh: float | None = None
    baseload_diff_kwh: float | None = None
    flex_diff_kwh: float | None = None

    @property
    def label(self) -> str:
        return self.window_end.strftime("%Y-%m-%d %H:%M")


@dataclass
class PlausibilityReport:
    results: list[PlausibilityResult] = field(default_factory=list)

    @property
    def failed(self) -> list[PlausibilityResult]:
        return [r for r in self.results if not r.ok]

    def add(self, result: PlausibilityResult) -> None:
        self.results.append(result)


def _consumption_within_tolerance(historical_kwh: float, optimized_kwh: float) -> bool:
    diff = abs(optimized_kwh - historical_kwh)
    if diff <= CONSUMPTION_TOLERANCE_KWH:
        return True
    if historical_kwh <= 0:
        return diff <= CONSUMPTION_TOLERANCE_KWH
    return (diff / historical_kwh) <= CONSUMPTION_TOLERANCE_REL


def _standby_kwh_in_rows(chart_rows: list[dict], meta: dict) -> float:
    """ESS standby energy included in Verbrauch-Prognose but not in cons_data."""
    from optimizer.slot_duration import energy_kwh_from_kw

    standby_kw = max(0.0, float(meta.get("standby_power_kw") or 0.0))
    if standby_kw <= 0.0 or not chart_rows:
        return 0.0
    return energy_kwh_from_kw(standby_kw for _ in chart_rows)


def _plausibility_reference_values(
    meta: dict,
    flexible_consumers: list | None,
) -> tuple[float, float, float, dict[str, float]]:
    """Referenz-kWh für Plausibilität (spec vs. geloggt)."""
    from house_config.planning_flex_bridge import PROFILE_SPEC

    source = meta.get("consumption_source", "logged_day")
    if source == PROFILE_SPEC:
        reference_kwh = float(meta["spec_total_kwh"])
        reference_baseload = float(meta["spec_baseload_kwh"])
        flex_targets = dict(meta.get("spec_flex_targets_kwh") or {})
    else:
        reference_kwh = float(meta["historical_total_kwh"])
        flex_targets = dict(
            meta.get("historical_totals") or meta.get("consumer_daily_targets_kwh", {})
        )
        reference_baseload = float(
            meta.get("baseload_kwh")
            if meta.get("baseload_kwh") is not None
            else derive_historical_baseload_kwh(reference_kwh, flex_targets)
        )
    if flexible_consumers:
        flex_ids = {consumer["id"] for consumer in flexible_consumers}
        flex_targets = {
            key: value for key, value in flex_targets.items() if key in flex_ids
        }
    reference_flex = round(sum(float(v) for v in flex_targets.values()), 3)
    return reference_kwh, reference_baseload, reference_flex, flex_targets


def validate_window_consumption(
    chart_rows: list[dict],
    meta: dict,
) -> PlausibilityResult:
    """Prüft Grundlast und Flex getrennt gegen Referenz-24h-Werte (Spec oder Log)."""
    flexible_consumers = meta.get("_flexible_consumers")
    reference_kwh, reference_baseload, reference_flex, _flex_targets = (
        _plausibility_reference_values(meta, flexible_consumers)
    )

    optimized_baseload = baseload_kwh_from_chart_rows(
        chart_rows,
        flexible_consumers=flexible_consumers,
    )
    standby_kwh = _standby_kwh_in_rows(chart_rows, meta)
    if standby_kwh:
        optimized_baseload = round(max(0.0, optimized_baseload - standby_kwh), 3)
    delivered_flex = _delivered_flex_kwh_from_rows(
        chart_rows,
        flexible_consumers=flexible_consumers,
    )
    optimized_flex = round(sum(delivered_flex.values()), 3)
    # Sunrise: deadline-flex often sits in SA₀→SA₁ foresight (book cut drops it).
    if meta.get("plausibility_optimized_flex_kwh") is not None:
        optimized_flex = round(float(meta["plausibility_optimized_flex_kwh"]), 3)
    optimized_kwh = round(optimized_baseload + optimized_flex, 3)

    baseload_ok = _consumption_within_tolerance(
        reference_baseload, optimized_baseload
    )
    flex_ok = _consumption_within_tolerance(reference_flex, optimized_flex)
    total_ok = _consumption_within_tolerance(reference_kwh, optimized_kwh)
    ok = baseload_ok and flex_ok and total_ok

    return PlausibilityResult(
        window_end=meta["window_end"],
        historical_kwh=reference_kwh,
        optimized_kwh=optimized_kwh,
        diff_kwh=round(abs(optimized_kwh - reference_kwh), 3),
        ok=ok,
        historical_baseload_kwh=reference_baseload,
        optimized_baseload_kwh=optimized_baseload,
        historical_flex_kwh=reference_flex,
        optimized_flex_kwh=optimized_flex,
        baseload_diff_kwh=round(abs(optimized_baseload - reference_baseload), 3),
        flex_diff_kwh=round(abs(optimized_flex - reference_flex), 3),
    )


def print_plausibility_report(report: PlausibilityReport) -> None:
    total = len(report.results)
    failed = report.failed
    ok_count = total - len(failed)

    print("\n=== PLAUSIBILISIERUNG (24h-Gesamtverbrauch) ===")
    print(
        f"  {ok_count}/{total} Fenster OK "
        f"(Toleranz: {CONSUMPTION_TOLERANCE_KWH} kWh oder "
        f"{CONSUMPTION_TOLERANCE_REL:.0%} relativ)"
    )
    if failed:
        print(f"  WARN: {len(failed)} Fenster ausserhalb der Toleranz:")
        for item in failed[:10]:
            detail = (
                f"    Ende {item.label}: historisch={item.historical_kwh:.2f} kWh, "
                f"optimiert={item.optimized_kwh:.2f} kWh, Delta={item.diff_kwh:.2f} kWh"
            )
            if item.baseload_diff_kwh is not None and item.flex_diff_kwh is not None:
                detail += (
                    f" | Grundlast Δ={item.baseload_diff_kwh:.2f}, "
                    f"Flex Δ={item.flex_diff_kwh:.2f}"
                )
            print(detail)
        if len(failed) > 10:
            print(f"    ... und {len(failed) - 10} weitere")
    print("===============================================")


