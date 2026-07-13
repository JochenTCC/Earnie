"""Szenario-Verbrauchsserien für die Szenarien-Explorer-Visualisierung."""
from __future__ import annotations

import pandas as pd

from data.consumption_profiles import _consumer_id, modeled_consumer_kw_at_datetime
from data.cons_data_house_profile import hourly_kw_by_consumer_for_timestamps
from ui.consumption_display.types import (
    BaselineOptimizedOverlay,
    ScenarioConsumerOverlayBundle,
    ScenarioConsumerSeries,
)

_BASELOAD_KEY = "baseload"
_TIMING_SHIFT_ENERGY_TOLERANCE_KWH = 1.0
_TIMING_SHIFT_HOURLY_L1_KWH = 5.0


def _consumer_labels_from_profile(profile: dict) -> dict[str, str]:
    labels = {_BASELOAD_KEY: "Basislast"}
    for index, consumer in enumerate(profile.get("consumers", [])):
        cid = _consumer_id(consumer, index)
        labels[cid] = str(consumer.get("label") or cid)
    return labels


def _ordered_consumer_ids(profiles: list[dict]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for profile in profiles:
        for index, consumer in enumerate(profile.get("consumers", [])):
            cid = _consumer_id(consumer, index)
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
    if _BASELOAD_KEY not in seen:
        ordered.append(_BASELOAD_KEY)
    return ordered


def _align_consumer_series(
    by_consumer: dict[str, list[float]],
    consumer_ids: list[str],
    hour_count: int,
) -> dict[str, list[float]]:
    zeroes = [0.0] * hour_count
    return {
        consumer_id: list(by_consumer.get(consumer_id, zeroes))
        for consumer_id in consumer_ids
    }


def build_scenario_consumer_overlays(
    scenarios: dict[str, dict],
    labels: dict[str, str],
    timestamps: list[str],
) -> ScenarioConsumerOverlayBundle | None:
    """Modellierten Verbrauch je Verbraucher und Szenario (Hausprofil)."""
    profiles: list[dict] = []
    scenario_series: list[ScenarioConsumerSeries] = []
    hour_count = len(timestamps)

    for scenario_id, settings in scenarios.items():
        profile = settings.get("_house_profile")
        if not isinstance(profile, dict):
            continue
        profiles.append(profile)
        by_consumer = hourly_kw_by_consumer_for_timestamps(profile, timestamps)
        scenario_series.append(
            ScenarioConsumerSeries(
                label=labels.get(scenario_id, scenario_id),
                consumer_kw=by_consumer,
            )
        )

    if not scenario_series:
        return None

    consumer_ids = _ordered_consumer_ids(profiles)
    consumer_labels = {_BASELOAD_KEY: "Basislast"}
    for profile in profiles:
        consumer_labels.update(_consumer_labels_from_profile(profile))

    aligned_scenarios = tuple(
        ScenarioConsumerSeries(
            label=series.label,
            consumer_kw=_align_consumer_series(series.consumer_kw, consumer_ids, hour_count),
        )
        for series in scenario_series
    )
    return ScenarioConsumerOverlayBundle(
        consumer_ids=consumer_ids,
        consumer_labels=consumer_labels,
        scenarios=aligned_scenarios,
    )


def _flex_kw_columns(hourly_df: pd.DataFrame) -> list[str]:
    skip = {"consumption_kw", "baseload_kw", "batt_action_kw"}
    return sorted(
        col
        for col in hourly_df.columns
        if col.endswith("_kw") and col not in skip
    )


def _align_hourly_series(
    hourly_df: pd.DataFrame,
    scenario_id: str,
    timestamps: list[str],
    *,
    value_columns: list[str],
) -> dict[str, list[float]]:
    part = hourly_df.loc[hourly_df["scenario_id"] == scenario_id].copy()
    if part.empty or "ts" not in part.columns:
        return {col: [0.0] * len(timestamps) for col in value_columns}
    part["ts"] = pd.to_datetime(part["ts"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    part = part.drop_duplicates(subset=["ts"], keep="last").set_index("ts")
    aligned: dict[str, list[float]] = {}
    for col in value_columns:
        if col not in part.columns:
            aligned[col] = [0.0] * len(timestamps)
            continue
        aligned[col] = [
            round(float(part.loc[ts_raw, col]) if ts_raw in part.index else 0.0, 4)
            for ts_raw in timestamps
        ]
    return aligned


def optimized_kw_by_consumer_from_hourly(
    hourly_df: pd.DataFrame,
    scenario_id: str,
    timestamps: list[str],
    consumer_ids: list[str],
) -> dict[str, list[float]]:
    """Optimierte kW-Serien je Verbraucher aus backtesting_hourly.csv."""
    flex_cols = _flex_kw_columns(hourly_df)
    flex_by_id = {
        col[: -len("_kw")]: col
        for col in flex_cols
    }
    columns = ["baseload_kw", *flex_cols]
    aligned = _align_hourly_series(
        hourly_df,
        scenario_id,
        timestamps,
        value_columns=columns,
    )
    by_consumer: dict[str, list[float]] = {
        _BASELOAD_KEY: aligned.get("baseload_kw", [0.0] * len(timestamps)),
    }
    for consumer_id in consumer_ids:
        if consumer_id == _BASELOAD_KEY:
            continue
        col = flex_by_id.get(consumer_id)
        by_consumer[consumer_id] = (
            aligned.get(col, [0.0] * len(timestamps)) if col else [0.0] * len(timestamps)
        )
    return by_consumer


def hourly_log_has_consumption_columns(hourly_df: pd.DataFrame) -> bool:
    return "consumption_kw" in hourly_df.columns and "baseload_kw" in hourly_df.columns


def detect_period_timing_shift(
    baseline_kw: dict[str, list[float]],
    optimized_kw: dict[str, list[float]],
    *,
    energy_tolerance_kwh: float = _TIMING_SHIFT_ENERGY_TOLERANCE_KWH,
    hourly_l1_threshold_kwh: float = _TIMING_SHIFT_HOURLY_L1_KWH,
) -> bool:
    """True wenn Gesamtenergie ≈ gleich, aber stündliche Profile abweichen."""
    consumer_ids = set(baseline_kw) | set(optimized_kw)
    total_b = sum(sum(baseline_kw.get(cid, [])) for cid in consumer_ids)
    total_o = sum(sum(optimized_kw.get(cid, [])) for cid in consumer_ids)
    if abs(total_o - total_b) > energy_tolerance_kwh:
        return False
    l1 = 0.0
    for consumer_id in consumer_ids:
        baseline_series = baseline_kw.get(consumer_id, [])
        optimized_series = optimized_kw.get(consumer_id, [])
        hour_count = max(len(baseline_series), len(optimized_series))
        for index in range(hour_count):
            baseline_value = baseline_series[index] if index < len(baseline_series) else 0.0
            optimized_value = (
                optimized_series[index] if index < len(optimized_series) else 0.0
            )
            l1 += abs(baseline_value - optimized_value)
    return l1 >= hourly_l1_threshold_kwh


def _climate_for_overlay(settings: dict, profile: dict):
    """Open-Meteo-Klima nur wenn Hausprofil Koordinaten hat."""
    if profile.get("latitude") is None or profile.get("longitude") is None:
        return None
    from data.modeled_climate import ModeledClimateContext

    return ModeledClimateContext.from_scenario(settings)


def _split_optimized_baseload_for_overlay(
    profile: dict,
    timestamps: list[str],
    optimized_kw: dict[str, list[float]],
    *,
    climate,
) -> dict[str, list[float]]:
    """Trennt flache Grundlast von thermischem Overlay für den SE-Vergleichschart."""
    from datetime import datetime

    from house_config.planning_flex_bridge import profile_flat_baseload_kw

    flat_kw = round(profile_flat_baseload_kw(profile), 4)
    hour_count = len(timestamps)
    result = dict(optimized_kw)
    result[_BASELOAD_KEY] = [flat_kw] * hour_count

    thermal_ids = [
        str(consumer.get("id") or "")
        for consumer in profile.get("consumers", [])
        if consumer.get("type") == "thermal_annual" and consumer.get("id")
    ]
    if not thermal_ids:
        return result

    consumers_by_id = {
        str(consumer.get("id") or ""): consumer
        for consumer in profile.get("consumers", [])
    }
    for consumer_id in thermal_ids:
        consumer = consumers_by_id.get(consumer_id)
        if consumer is None:
            continue
        series: list[float] = []
        for ts_raw in timestamps:
            slot_dt = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
            series.append(
                round(
                    float(
                        modeled_consumer_kw_at_datetime(
                            consumer,
                            slot_dt,
                            climate=climate,
                        )
                    ),
                    4,
                )
            )
        result[consumer_id] = series
    return result


def build_baseline_optimized_overlay(
    scenarios: dict[str, dict],
    labels: dict[str, str],
    scenario_id: str,
    timestamps: list[str],
    hourly_df: pd.DataFrame,
) -> BaselineOptimizedOverlay | None:
    """Profil-Baseline (Spec) und optimierter Verbrauch für ein Szenario."""
    settings = scenarios.get(scenario_id)
    if not isinstance(settings, dict):
        return None
    profile = settings.get("_house_profile")
    if not isinstance(profile, dict):
        return None
    if not hourly_log_has_consumption_columns(hourly_df):
        return None

    climate = _climate_for_overlay(settings, profile)
    baseline_kw = hourly_kw_by_consumer_for_timestamps(
        profile,
        timestamps,
        climate=climate,
    )
    consumer_ids = list(baseline_kw.keys())
    if _BASELOAD_KEY not in consumer_ids:
        consumer_ids.append(_BASELOAD_KEY)
    consumer_labels = _consumer_labels_from_profile(profile)
    optimized_kw = optimized_kw_by_consumer_from_hourly(
        hourly_df,
        scenario_id,
        timestamps,
        consumer_ids,
    )
    optimized_kw = _split_optimized_baseload_for_overlay(
        profile,
        timestamps,
        optimized_kw,
        climate=climate,
    )
    return BaselineOptimizedOverlay(
        scenario_label=labels.get(scenario_id, scenario_id),
        consumer_ids=consumer_ids,
        consumer_labels=consumer_labels,
        baseline_kw=baseline_kw,
        optimized_kw=optimized_kw,
    )
