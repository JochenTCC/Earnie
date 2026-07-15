"""Tests für runtime/legacy flex-kW-Bridging."""
from __future__ import annotations

from settings.flexible_consumers import (
    flex_kw_lookup,
    flex_kw_pop_for_consumer,
    flex_kw_to_canonical,
    profile_column_id,
    runtime_consumer_id,
)


def test_flex_kw_lookup_prefers_runtime_key():
    consumer = {"id": "ev", "legacy_id": "eauto"}
    flex = {"eauto": 1.4, "ev": 0.1}
    assert flex_kw_lookup(flex, consumer) == 1.4


def test_flex_kw_lookup_falls_back_to_canonical():
    consumer = {"id": "ev", "legacy_id": "eauto"}
    assert flex_kw_lookup({"ev": 2.0}, consumer) == 2.0


def test_flex_kw_to_canonical_maps_runtime_keys():
    consumer = {"id": "ev", "legacy_id": "eauto", "name": "Smart"}
    result = flex_kw_to_canonical({"eauto": 1.4}, [consumer])
    assert result == {"ev": 1.4}


def test_flex_kw_pop_removes_both_keys():
    consumer = {"id": "ev", "legacy_id": "eauto"}
    flex = {"eauto": 1.0, "ev": 0.5}
    removed = flex_kw_pop_for_consumer(flex, consumer)
    assert removed == 1.0
    assert flex == {}


def test_profile_column_id_uses_legacy():
    consumer = {"id": "ev", "legacy_id": "eauto"}
    assert profile_column_id(consumer) == runtime_consumer_id(consumer) == "eauto"
