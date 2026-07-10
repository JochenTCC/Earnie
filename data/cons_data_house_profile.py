"""Hausprofil-Auflösung und Synthese für cons_data_hourly.csv."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

import config
from data.consumption_profiles import build_modeled_hourly_kw_by_consumer
from house_config.profiles_store import load_house_profiles_document
from runtime_store.persist_paths import resolve_house_profiles_json_path


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


def expected_cons_data_consumer_ids() -> list[str]:
    """Verbraucher-IDs für cons_data: config.flexible_consumers oder Hausprofil."""
    flex_ids = [c["id"] for c in config.get_flexible_consumers()]
    if flex_ids:
        return flex_ids
    profile = resolve_runtime_house_profile()
    if not profile:
        return []
    return [str(c["id"]) for c in profile.get("consumers", []) if c.get("id")]


def consumer_labels_for_ids(consumer_ids: list[str]) -> dict[str, str]:
    profile = resolve_runtime_house_profile()
    if not profile:
        return {cid: cid for cid in consumer_ids}
    by_id = {
        str(c["id"]): str(c.get("label") or c["id"])
        for c in profile.get("consumers", [])
        if c.get("id")
    }
    return {cid: by_id.get(cid, cid) for cid in consumer_ids}


def build_synthetic_dataframe_from_house_profile(
    profile: dict,
    *,
    start: date,
    end: date,
    kwp: float,
    source: str,
    pv_kw_for_hour,
) -> pd.DataFrame:
    """Stündliche cons_data aus modelliertem Hausprofil (Verbraucher + Basislast)."""
    start_dt = datetime.combine(start, time(0))
    end_dt = datetime.combine(end, time(23))
    hours = int((end_dt - start_dt).total_seconds() // 3600) + 1
    if hours <= 0:
        raise ValueError("Ungültiger Zeitraum für cons_data-Synthese.")

    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    baseload_series = by_consumer.pop("baseload")
    consumer_ids = list(by_consumer.keys())
    timestamps = pd.date_range(start_dt, periods=hours, freq="h")

    rows: list[dict] = []
    for index, ts in enumerate(timestamps):
        flex_vals = {cid: float(by_consumer[cid][index]) for cid in consumer_ids}
        flex_sum = sum(flex_vals.values())
        base = float(baseload_series[index])
        rows.append(
            {
                "timestamp": ts,
                "total_kw": round(base + flex_sum, 3),
                "baseload_kw": round(base, 3),
                "pv_kw": pv_kw_for_hour(ts.hour, ts.month, kwp),
                "source": source,
                **{f"{cid}_kw": round(flex_vals[cid], 3) for cid in consumer_ids},
            }
        )
    return pd.DataFrame(rows).set_index("timestamp")
