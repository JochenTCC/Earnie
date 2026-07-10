"""Monats- und Perioden-Aggregation für Verbrauchs-Charts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from ui.consumption_display.types import ConsumptionSeriesBundle
from ui.consumption_validation_charts import format_iso_week_label, iso_weeks_in_series


def parse_timestamp(ts_raw: str) -> datetime:
    return datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])


def months_in_timestamps(
    timestamps: list[str],
    *,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> list[str]:
    """Kalendermonate (YYYY-MM) in Reihenfolge des ersten Vorkommens."""
    months: list[str] = []
    seen: set[str] = set()
    for ts_raw in timestamps:
        ts = parse_timestamp(ts_raw)
        if nav_bounds is not None:
            if ts < nav_bounds[0] or ts > nav_bounds[1]:
                continue
        key = f"{ts.year}-{ts.month:02d}"
        if key not in seen:
            seen.add(key)
            months.append(key)
    return months


def iso_weeks_in_timestamps(
    timestamps: list[str],
    *,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> list[tuple[int, int]]:
    """ISO-Kalenderwochen aus Timestamps; optional auf nav_bounds gefiltert."""
    if nav_bounds is None:
        return iso_weeks_in_series([(ts, 0.0) for ts in timestamps])
    filtered = [
        (ts, 0.0)
        for ts in timestamps
        if nav_bounds[0] <= parse_timestamp(ts) <= nav_bounds[1]
    ]
    return iso_weeks_in_series(filtered)


def format_month_label(month_key: str) -> str:
    year_str, month_str = month_key.split("-", 1)
    return f"{month_str}/{year_str}"


def monthly_kwh_from_series(values: list[float], timestamps: list[str]) -> dict[str, float]:
    monthly: dict[str, float] = defaultdict(float)
    for ts_raw, power_kw in zip(timestamps, values):
        ts = parse_timestamp(ts_raw)
        key = f"{ts.year}-{ts.month:02d}"
        monthly[key] += float(power_kw)
    return dict(sorted(monthly.items()))


def monthly_kwh_by_consumer(
    bundle: ConsumptionSeriesBundle,
) -> dict[str, dict[str, float]]:
    """Monat → Verbraucher-ID → kWh."""
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for consumer_id, series in bundle.consumer_series.items():
        for month, kwh in monthly_kwh_from_series(series, bundle.timestamps).items():
            result[month][consumer_id] = kwh
    baseload_monthly = monthly_kwh_from_series(bundle.baseload, bundle.timestamps)
    for month, kwh in baseload_monthly.items():
        result[month]["baseload"] = kwh
    return {month: dict(values) for month, values in sorted(result.items())}


def monthly_pv_kwh(bundle: ConsumptionSeriesBundle) -> dict[str, float]:
    if bundle.pv is None:
        return {}
    return monthly_kwh_from_series(bundle.pv, bundle.timestamps)


def monthly_total_kwh(bundle: ConsumptionSeriesBundle) -> dict[str, float]:
    totals = [0.0] * bundle.hour_count()
    for series in bundle.consumer_series.values():
        totals = [a + b for a, b in zip(totals, series)]
    totals = [a + b for a, b in zip(totals, bundle.baseload)]
    return monthly_kwh_from_series(totals, bundle.timestamps)


def slice_bundle_for_month(
    bundle: ConsumptionSeriesBundle,
    month_key: str,
) -> ConsumptionSeriesBundle:
    year_str, month_str = month_key.split("-", 1)
    year, month = int(year_str), int(month_str)
    indices = [
        index
        for index, ts_raw in enumerate(bundle.timestamps)
        if parse_timestamp(ts_raw).year == year and parse_timestamp(ts_raw).month == month
    ]
    return _slice_bundle(bundle, indices)


def slice_bundle_for_iso_week(
    bundle: ConsumptionSeriesBundle,
    *,
    iso_year: int,
    iso_week: int,
) -> ConsumptionSeriesBundle:
    indices = [
        index
        for index, ts_raw in enumerate(bundle.timestamps)
        if parse_timestamp(ts_raw).isocalendar()[:2] == (iso_year, iso_week)
    ]
    return _slice_bundle(bundle, indices)


def _slice_bundle(bundle: ConsumptionSeriesBundle, indices: list[int]) -> ConsumptionSeriesBundle:
    if not indices:
        return ConsumptionSeriesBundle(
            timestamps=[],
            consumer_series={cid: [] for cid in bundle.consumer_series},
            baseload=[],
            pv=None if bundle.pv is None else [],
            actual_total=None if bundle.actual_total is None else [],
            consumer_labels=dict(bundle.consumer_labels),
        )
    return ConsumptionSeriesBundle(
        timestamps=[bundle.timestamps[i] for i in indices],
        consumer_series={
            cid: [series[i] for i in indices]
            for cid, series in bundle.consumer_series.items()
        },
        baseload=[bundle.baseload[i] for i in indices],
        pv=None if bundle.pv is None else [bundle.pv[i] for i in indices],
        actual_total=(
            None
            if bundle.actual_total is None
            else [bundle.actual_total[i] for i in indices]
        ),
        consumer_labels=dict(bundle.consumer_labels),
    )


def annual_kwh_from_bundle(bundle: ConsumptionSeriesBundle) -> float:
    return sum(monthly_total_kwh(bundle).values())


def annual_kwh_actual(bundle: ConsumptionSeriesBundle) -> float:
    if bundle.actual_total is None:
        return 0.0
    return sum(monthly_kwh_from_series(bundle.actual_total, bundle.timestamps).values())
