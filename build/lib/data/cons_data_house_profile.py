"""Hausprofil-Auflösung und Synthese für cons_data_hourly.csv."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time
from typing import TYPE_CHECKING

import pandas as pd

import config
from settings.flexible_consumers import normalize_consumer, runtime_consumer_id
from data.consumption_profiles import (
    _consumer_id,
    _modeled_hour_index,
    modeled_consumer_kw_at_datetime,
)
from house_config.consumption_csv import load_hourly_profile_csv
from house_config.profiles_store import load_house_profiles_document
from runtime_store.persist_paths import resolve_house_profiles_json_path

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext

def _parse_hourly_timestamp(ts_raw: str) -> datetime:
    return datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])


def total_kw_at_datetime(profile: dict, slot_dt: datetime) -> float:
    """Gesamtverbrauch (kW) zum Kalenderzeitpunkt aus Hausprofil."""
    csv_path = profile.get("total_profile_csv", "")
    if csv_path:
        series = load_hourly_profile_csv(csv_path)
        hour_index = _modeled_hour_index(slot_dt)
        if hour_index < len(series):
            return float(series[hour_index][1])
        return 0.0
    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / 8760.0
    flex_sum = sum(
        modeled_consumer_kw_at_datetime(consumer, slot_dt)
        for consumer in profile.get("consumers", [])
    )
    return baseload_kw + flex_sum


def hourly_kw_by_consumer_for_timestamps(
    profile: dict,
    timestamps: list[str],
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, list[float]]:
    """Stündlicher kW je Verbraucher + Basislast, kalenderbasiert wie cons_data-Synthese."""
    consumers = list(profile.get("consumers", []))
    consumer_ids = [_consumer_id(consumer, index) for index, consumer in enumerate(consumers)]
    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / 8760.0
    series: dict[str, list[float]] = {cid: [] for cid in consumer_ids}
    baseload_series: list[float] = []
    for ts_raw in timestamps:
        slot_dt = _parse_hourly_timestamp(ts_raw)
        for index, cid in enumerate(consumer_ids):
            series[cid].append(
                modeled_consumer_kw_at_datetime(
                    consumers[index],
                    slot_dt,
                    climate=climate,
                )
            )
        baseload_series.append(baseload_kw)
    series["baseload"] = baseload_series
    return series


def hourly_total_kw_for_timestamps(
    profile: dict,
    timestamps: list[str],
) -> list[float]:
    """Gesamtverbrauch (kW) je Timestamp-String, kalenderbasiert wie cons_data-Synthese."""
    return [
        total_kw_at_datetime(profile, _parse_hourly_timestamp(ts_raw))
        for ts_raw in timestamps
    ]


def resolve_runtime_house_profile() -> dict | None:
    """Aktives Hausprofil aus runtime_settings.house_profile_id."""
    from ui.house_config_io import get_runtime_scenario_refs, load_house_profiles

    profile_id = str(get_runtime_scenario_refs().get("house_profile_id", "") or "").strip()
    if not profile_id:
        return None
    profiles = load_house_profiles().get("profiles", {})
    if isinstance(profiles, dict):
        return profiles.get(profile_id)
    if isinstance(profiles, list):
        return next((item for item in profiles if item.get("id") == profile_id), None)
    return None


def _configured_flexible_consumer_ids() -> list[str]:
    """IDs aus config.flexible_consumers (ohne Planungs-Merge) für cons_data-Spalten."""
    raw = config.CONFIG._raw_config.get("flexible_consumers", [])
    consumers = [
        normalize_consumer(entry)
        for entry in raw
        if isinstance(entry, dict) and entry.get("id")
    ]
    return [runtime_consumer_id(c) for c in consumers]


def _house_profile_consumer_ids(profile: dict) -> list[str]:
    """Alle modellierten Verbraucher-IDs — identisch zur Synthese."""
    from data.consumption_profiles import _consumer_id

    return [
        _consumer_id(consumer, index)
        for index, consumer in enumerate(profile.get("consumers", []))
    ]


def expected_cons_data_consumer_ids() -> list[str]:
    """Verbraucher-IDs für cons_data: config.flexible_consumers oder Hausprofil."""
    flex_ids = _configured_flexible_consumer_ids()
    if flex_ids:
        return flex_ids
    profile = resolve_runtime_house_profile()
    if not profile:
        return []
    return _house_profile_consumer_ids(profile)


def consumer_labels_for_ids(consumer_ids: list[str]) -> dict[str, str]:
    labels = {cid: cid for cid in consumer_ids}
    config_by_runtime_id = {
        runtime_consumer_id(c): str(c.get("name") or c["id"])
        for c in config.get_flexible_consumers()
        if c.get("id")
    }
    for cid in consumer_ids:
        if cid in config_by_runtime_id:
            labels[cid] = config_by_runtime_id[cid]
    profile = resolve_runtime_house_profile()
    if not profile:
        return labels
    by_id = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in profile.get("consumers", [])
        if c.get("id")
    }
    for cid in consumer_ids:
        if cid not in config_by_runtime_id:
            labels[cid] = by_id.get(cid, labels[cid])
    return labels


def build_synthetic_dataframe_from_house_profile(
    profile: dict,
    *,
    start: date,
    end: date,
    kwp: float,
    source: str,
    climate: ModeledClimateContext | None = None,
    pv_kw_at_datetime: Callable[[datetime], float] | None = None,
) -> pd.DataFrame:
    """Stündliche cons_data aus modelliertem Hausprofil (Verbraucher + Basislast)."""
    if climate is None and pv_kw_at_datetime is None:
        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.for_house_profile(profile, kwp=kwp)
    start_dt = datetime.combine(start, time(0))
    end_dt = datetime.combine(end, time(23))
    hours = int((end_dt - start_dt).total_seconds() // 3600) + 1
    if hours <= 0:
        raise ValueError("Ungültiger Zeitraum für cons_data-Synthese.")

    baseload_kwh = float(profile.get("baseload_kwh", 0.0) or 0.0)
    baseload_kw = baseload_kwh / 8760.0
    consumers = list(profile.get("consumers", []))
    consumer_ids = [_consumer_id(consumer, index) for index, consumer in enumerate(consumers)]
    timestamps = pd.date_range(start_dt, periods=hours, freq="h")

    rows: list[dict] = []
    for ts in timestamps:
        slot_dt = ts.to_pydatetime()
        flex_vals = {
            cid: modeled_consumer_kw_at_datetime(
                consumers[index],
                slot_dt,
                climate=climate,
            )
            for index, cid in enumerate(consumer_ids)
        }
        flex_sum = sum(flex_vals.values())
        if climate is not None:
            pv_kw = climate.pv_kw_at(slot_dt)
        else:
            pv_kw = pv_kw_at_datetime(slot_dt)
        rows.append(
            {
                "timestamp": ts,
                "total_kw": round(baseload_kw + flex_sum, 3),
                "baseload_kw": round(baseload_kw, 3),
                "pv_kw": pv_kw,
                "source": source,
                **{f"{cid}_kw": round(flex_vals[cid], 3) for cid in consumer_ids},
            }
        )
    return pd.DataFrame(rows).set_index("timestamp")