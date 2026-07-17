"""Datenadapter für die drei Verbrauchs-UI-Modi."""
from __future__ import annotations

import pandas as pd

from data.consumption_profiles import build_modeled_hourly_kw_by_consumer
from data.cons_data_house_profile import (
    consumer_labels_for_ids,
    expected_cons_data_consumer_ids,
)
from ui.consumption_display.types import ConsumptionSeriesBundle
from ui.consumption_validation_charts import csv_series_to_monthly_kwh


def bundle_from_modeled_profile(
    profile: dict,
    *,
    hours: int | None = None,
) -> ConsumptionSeriesBundle:
    # UI "Verbrauchsprofil (Modell)": never use meter residual from total_profile_csv.
    model_profile = {**profile, "total_profile_csv": ""}
    resolved_hours = hours if hours is not None else 8760
    by_consumer = build_modeled_hourly_kw_by_consumer(model_profile, hours=resolved_hours)
    baseload = by_consumer.pop("baseload")
    timestamps = _hourly_timestamps(resolved_hours)
    labels = _consumer_labels_from_profile(profile)
    return ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series=by_consumer,
        baseload=baseload,
        consumer_labels=labels,
    )


def bundle_from_csv_validation(
    series: list[tuple[str, float]],
    profile: dict,
) -> ConsumptionSeriesBundle:
    """Ist = CSV; Modell = independent profile (not meter residual)."""
    from data.consumption_profiles import build_modeled_kw_for_timestamps

    timestamps = [ts for ts, _ in series]
    actual_total = [float(kw) for _, kw in series]
    by_consumer = build_modeled_kw_for_timestamps(profile, timestamps)
    baseload = by_consumer.pop("baseload")
    labels = _consumer_labels_from_profile(profile)
    return ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series=by_consumer,
        baseload=baseload,
        actual_total=actual_total,
        consumer_labels=labels,
    )


def bundle_from_cons_data(df: pd.DataFrame) -> ConsumptionSeriesBundle:
    if df.empty:
        raise ValueError("cons_data DataFrame ist leer.")
    timestamps = [ts.strftime("%Y-%m-%d %H:%M:%S") for ts in df.index]
    consumer_ids = _cons_data_consumer_ids(df)
    consumer_series = {
        cid: df[f"{cid}_kw"].astype(float).tolist() for cid in consumer_ids
    }
    baseload = df["baseload_kw"].astype(float).tolist()
    pv = df["pv_kw"].astype(float).tolist() if "pv_kw" in df.columns else None
    labels = consumer_labels_for_ids(consumer_ids)
    return ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series=consumer_series,
        baseload=baseload,
        pv=pv,
        consumer_labels=labels,
    )


def with_modeled_pv_by_system(
    bundle: ConsumptionSeriesBundle,
    scenario_params: dict | None,
) -> ConsumptionSeriesBundle:
    """Attach per-PV modeled series from one scenario; ``bundle.pv`` stays the sum."""
    planning = (scenario_params or {}).get("_planning_pv_systems")
    if not isinstance(planning, list) or not planning:
        return bundle
    if not bundle.timestamps:
        return bundle

    from datetime import datetime

    from data.modeled_climate import ModeledClimateContext

    climate = ModeledClimateContext.from_scenario(scenario_params or {})
    slots = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for ts in bundle.timestamps]
    by_system = climate.pv_kw_by_system_for_slots(slots)
    if not by_system:
        return bundle
    return ConsumptionSeriesBundle(
        timestamps=bundle.timestamps,
        consumer_series=bundle.consumer_series,
        baseload=bundle.baseload,
        pv=bundle.pv,
        actual_total=bundle.actual_total,
        consumer_labels=dict(bundle.consumer_labels),
        pv_by_system=by_system,
        pv_system_labels=climate.pv_system_labels(),
    )


def collect_unique_planning_pv(scenarios: dict[str, dict]) -> list[dict]:
    """Union of ``_planning_pv_systems`` across scenarios (dedupe by id, first wins)."""
    ordered: list[dict] = []
    seen: set[str] = set()
    for settings in scenarios.values():
        if not isinstance(settings, dict):
            continue
        planning = settings.get("_planning_pv_systems")
        if not isinstance(planning, list):
            continue
        for item in planning:
            if not isinstance(item, dict):
                continue
            pv_id = str(item.get("id") or "").strip()
            if not pv_id or pv_id in seen:
                continue
            seen.add(pv_id)
            ordered.append(dict(item))
    return ordered


def pv_config_key(pv_ids: frozenset[str] | set[str] | list[str]) -> str:
    """Stable key for a unique PV configuration (sorted ids joined by ``+``)."""
    return "+".join(sorted(pv_ids))


def joined_pv_config_label(pv_ids: frozenset[str] | set[str], labels: dict[str, str]) -> str:
    """Joined legend name: labels sorted alphabetically, separated by `` + ``."""
    return " + ".join(sorted(str(labels.get(pv_id) or pv_id) for pv_id in pv_ids))


def _planning_pv_ids(settings: dict) -> frozenset[str]:
    planning = settings.get("_planning_pv_systems")
    if not isinstance(planning, list):
        return frozenset()
    ids: set[str] = set()
    for item in planning:
        if not isinstance(item, dict):
            continue
        pv_id = str(item.get("id") or "").strip()
        if pv_id:
            ids.add(pv_id)
    return frozenset(ids)


def collect_unique_pv_configs(scenarios: dict[str, dict]) -> list[frozenset[str]]:
    """Unique frozensets of PV ids across scenarios (first-seen order)."""
    ordered: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()
    for settings in scenarios.values():
        if not isinstance(settings, dict):
            continue
        config = _planning_pv_ids(settings)
        if not config or config in seen:
            continue
        seen.add(config)
        ordered.append(config)
    return ordered


def _sum_hourly_series(series_list: list[list[float]]) -> list[float]:
    if not series_list:
        return []
    length = len(series_list[0])
    return [sum(series[index] for series in series_list) for index in range(length)]


def _scenario_settings_for_pv(
    scenarios: dict[str, dict],
    pv_id: str,
    *,
    prefer_scenario_id: str | None,
) -> dict | None:
    if prefer_scenario_id and prefer_scenario_id in scenarios:
        settings = scenarios[prefer_scenario_id]
        planning = settings.get("_planning_pv_systems") if isinstance(settings, dict) else None
        if isinstance(planning, list) and any(
            isinstance(item, dict) and str(item.get("id") or "").strip() == pv_id
            for item in planning
        ):
            return settings
    for settings in scenarios.values():
        if not isinstance(settings, dict):
            continue
        planning = settings.get("_planning_pv_systems")
        if not isinstance(planning, list):
            continue
        if any(
            isinstance(item, dict) and str(item.get("id") or "").strip() == pv_id
            for item in planning
        ):
            return settings
    return None


def with_modeled_pv_from_all_scenarios(
    bundle: ConsumptionSeriesBundle,
    scenarios: dict[str, dict] | None,
    *,
    live_scenario_id: str | None = None,
) -> ConsumptionSeriesBundle:
    """Attach per-PV series plus unique config sums across scenarios."""
    if not scenarios or not bundle.timestamps:
        return bundle
    unique = collect_unique_planning_pv(scenarios)
    if not unique:
        return bundle

    from datetime import datetime

    from data.modeled_climate import ModeledClimateContext

    slots = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for ts in bundle.timestamps]
    by_system: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    for pv in unique:
        pv_id = str(pv.get("id") or "").strip()
        if not pv_id:
            continue
        settings = _scenario_settings_for_pv(
            scenarios,
            pv_id,
            prefer_scenario_id=live_scenario_id,
        )
        if settings is None:
            continue
        single = dict(settings)
        single["_planning_pv_systems"] = [pv]
        climate = ModeledClimateContext.from_scenario(single)
        series_map = climate.pv_kw_by_system_for_slots(slots)
        values = series_map.get(pv_id)
        if values is None:
            continue
        by_system[pv_id] = values
        labels[pv_id] = str(pv.get("label") or pv_id)

    if not by_system:
        return bundle

    by_config: dict[str, list[float]] = {}
    config_labels: dict[str, str] = {}
    for config in collect_unique_pv_configs(scenarios):
        available = frozenset(pv_id for pv_id in config if pv_id in by_system)
        if not available:
            continue
        key = pv_config_key(available)
        by_config[key] = _sum_hourly_series([by_system[pv_id] for pv_id in sorted(available)])
        config_labels[key] = joined_pv_config_label(available, labels)

    return ConsumptionSeriesBundle(
        timestamps=bundle.timestamps,
        consumer_series=bundle.consumer_series,
        baseload=bundle.baseload,
        pv=bundle.pv,
        actual_total=bundle.actual_total,
        consumer_labels=dict(bundle.consumer_labels),
        pv_by_system=by_system,
        pv_system_labels=labels,
        pv_by_config=by_config,
        pv_config_labels=config_labels,
    )


def actual_monthly_from_csv(series: list[tuple[str, float]]) -> dict[str, float]:
    return csv_series_to_monthly_kwh(series)


def _cons_data_consumer_ids(df: pd.DataFrame) -> list[str]:
    skip = {"total", "baseload", "pv"}
    present = [
        col[: -len("_kw")]
        for col in df.columns
        if col.endswith("_kw") and col[: -len("_kw")] not in skip
    ]
    configured = expected_cons_data_consumer_ids()
    if configured:
        matched = [cid for cid in configured if f"{cid}_kw" in df.columns]
        if matched:
            return matched
    return present


def _consumer_labels_from_profile(profile: dict) -> dict[str, str]:
    labels: dict[str, str] = {"baseload": "Basislast"}
    for consumer in profile.get("consumers", []):
        cid = consumer.get("id") or consumer.get("label")
        if cid:
            labels[str(cid)] = str(consumer.get("label") or cid)
    return labels


def _hourly_timestamps(hours: int) -> list[str]:
    from datetime import datetime, timedelta

    start = datetime(2023, 1, 1, 0, 0, 0)
    return [
        (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(hours)
    ]
