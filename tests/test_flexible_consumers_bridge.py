"""Tests für kanonische (single-key) flex-kW-Lookups — Dual-Key-Bridge entfernt."""
from __future__ import annotations

import pytest

from settings.flexible_consumers import (
    flex_kw_lookup,
    flex_kw_pop_for_consumer,
    flex_kw_to_canonical,
    profile_column_id,
    reject_legacy_id,
    runtime_consumer_id,
)


def test_flex_kw_lookup_uses_canonical_id_only():
    consumer = {"id": "ev"}
    assert flex_kw_lookup({"eauto": 1.4, "ev": 0.1}, consumer) == 0.1


def test_flex_kw_lookup_ignores_legacy_key():
    assert flex_kw_lookup({"eauto": 1.4}, {"id": "ev"}) == 0.0


def test_flex_kw_to_canonical_keeps_canonical_keys():
    consumer = {"id": "ev", "name": "Smart"}
    assert flex_kw_to_canonical({"ev": 1.4, "eauto": 9.9}, [consumer]) == {"ev": 1.4}


def test_flex_kw_pop_removes_canonical_key_only():
    flex = {"eauto": 1.0, "ev": 0.5}
    assert flex_kw_pop_for_consumer(flex, {"id": "ev"}) == 0.5
    assert flex == {"eauto": 1.0}


def test_profile_column_id_is_canonical_id():
    consumer = {"id": "ev"}
    assert profile_column_id(consumer) == runtime_consumer_id(consumer) == "ev"


def test_reject_legacy_id_raises_with_german_hint():
    with pytest.raises(ValueError, match="legacy_id entfernt, kanonische id verwenden"):
        reject_legacy_id({"id": "ev", "legacy_id": "eauto"}, "ev")


def test_reject_legacy_id_passes_without_key():
    reject_legacy_id({"id": "ev"}, "ev")
