# tests/test_consumption_bundle_cache.py
from __future__ import annotations

from ui.consumption_display.bundle_cache import (
    csv_validation_probe_cache_key,
    fingerprint_ist_series,
    fingerprint_modeled_profile,
    get_or_build_consumption_bundle,
    modeled_profile_cache_key,
)
from ui.consumption_display.types import ConsumptionSeriesBundle


def _empty_bundle() -> ConsumptionSeriesBundle:
    return ConsumptionSeriesBundle(
        timestamps=[],
        consumer_series={},
        baseload=[],
    )


def test_fingerprint_modeled_profile_is_stable_and_order_independent():
    a = {"annual_kwh": 1000.0, "baseload_kwh": 100.0, "consumers": [{"id": "x"}]}
    b = {"consumers": [{"id": "x"}], "baseload_kwh": 100.0, "annual_kwh": 1000.0}
    assert fingerprint_modeled_profile(a) == fingerprint_modeled_profile(b)
    c = {**a, "baseload_kwh": 101.0}
    assert fingerprint_modeled_profile(a) != fingerprint_modeled_profile(c)


def test_get_or_build_hits_store_without_rebuilding():
    store: dict = {}
    calls = {"n": 0}

    def builder() -> ConsumptionSeriesBundle:
        calls["n"] += 1
        return _empty_bundle()

    key = modeled_profile_cache_key({"annual_kwh": 1.0, "consumers": []})
    first = get_or_build_consumption_bundle(key, builder, store=store)
    second = get_or_build_consumption_bundle(key, builder, store=store)
    assert first is second
    assert calls["n"] == 1


def test_get_or_build_misses_when_key_changes():
    store: dict = {}
    calls = {"n": 0}

    def builder() -> ConsumptionSeriesBundle:
        calls["n"] += 1
        return _empty_bundle()

    k1 = modeled_profile_cache_key({"annual_kwh": 1.0})
    k2 = modeled_profile_cache_key({"annual_kwh": 2.0})
    get_or_build_consumption_bundle(k1, builder, store=store)
    get_or_build_consumption_bundle(k2, builder, store=store)
    assert calls["n"] == 2
    assert len(store) == 2


def test_csv_probe_key_includes_path_and_series():
    profile = {"annual_kwh": 10.0, "baseload_kwh": 0.0, "consumers": []}
    series_a = [("2024-01-01T00:00:00", 1.0), ("2024-01-01T01:00:00", 2.0)]
    series_b = [("2024-01-01T00:00:00", 1.0), ("2024-01-01T01:00:00", 3.0)]
    k1 = csv_validation_probe_cache_key(
        profile,
        active_path="config:a.csv",
        series_fingerprint=fingerprint_ist_series(series_a),
    )
    k2 = csv_validation_probe_cache_key(
        profile,
        active_path="config:a.csv",
        series_fingerprint=fingerprint_ist_series(series_b),
    )
    k3 = csv_validation_probe_cache_key(
        profile,
        active_path="config:b.csv",
        series_fingerprint=fingerprint_ist_series(series_a),
    )
    assert k1 != k2
    assert k1 != k3
