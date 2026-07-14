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
    resolved_hours = hours if hours is not None else 8760
    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=resolved_hours)
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
    hours = len(series)
    modeled = bundle_from_modeled_profile(profile, hours=hours)
    actual_total = [float(kw) for _, kw in series]
    timestamps = [ts for ts, _ in series]
    return ConsumptionSeriesBundle(
        timestamps=timestamps,
        consumer_series=modeled.consumer_series,
        baseload=modeled.baseload,
        actual_total=actual_total,
        consumer_labels=modeled.consumer_labels,
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
