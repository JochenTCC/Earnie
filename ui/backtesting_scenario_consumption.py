"""Szenario-Verbrauchsserien für die Szenarien-Explorer-Visualisierung."""
from __future__ import annotations

from data.consumption_profiles import _consumer_id
from data.cons_data_house_profile import hourly_kw_by_consumer_for_timestamps
from ui.consumption_display.types import (
    ScenarioConsumerOverlayBundle,
    ScenarioConsumerSeries,
)

_BASELOAD_KEY = "baseload"


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
