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


def test_series_fingerprint_sees_values_between_the_sample_points():
    """Invert switches or a corrected import change values off the first/middle/last points."""
    base = [(f"2024-01-01T{h:02d}:00:00", 1.0) for h in range(10)]
    changed = list(base)
    changed[2] = (changed[2][0], -1.0)
    assert fingerprint_ist_series(base) != fingerprint_ist_series(changed)
    assert fingerprint_ist_series(base) == fingerprint_ist_series(list(base))


def test_profile_csv_lookup_rereads_a_rewritten_file(tmp_path):
    """Imports overwrite fixed paths; the CSV cache must follow the file, not the path."""
    import os
    from datetime import datetime

    from data.consumption_profiles import csv_kw_at_datetime
    from house_config.consumption_csv import write_canonical_hourly_csv

    path = tmp_path / "pv.csv"
    write_canonical_hourly_csv(str(path), [("2024-01-01 10:00:00", 1.0)])
    assert csv_kw_at_datetime(str(path), datetime(2024, 1, 1, 10)) == 1.0
    write_canonical_hourly_csv(
        str(path), [("2024-01-01 10:00:00", 2.5), ("2024-01-01 11:00:00", 0.0)]
    )
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert csv_kw_at_datetime(str(path), datetime(2024, 1, 1, 10)) == 2.5
