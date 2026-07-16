"""Unit tests for ui.tariff_filter_helpers pure filter helpers."""
from __future__ import annotations

from ui.tariff_filter_helpers import (
    filter_tariffs,
    lands_present,
    types_present,
    with_current_tariff,
)

_SAMPLE = [
    {"id": "at_spot", "land": "AT", "type": "spot_hourly", "label": "AT Spot"},
    {"id": "at_fix", "land": "AT", "type": "fixed_cent", "label": "AT Fix"},
    {"id": "de_spot", "land": "DE", "type": "spot_hourly", "label": "DE Spot"},
    {"id": "legacy", "type": "fixed", "label": "No land"},
]


def test_filter_by_land() -> None:
    result = filter_tariffs(_SAMPLE, land="AT")
    assert [item["id"] for item in result] == ["at_spot", "at_fix"]


def test_filter_by_type() -> None:
    result = filter_tariffs(_SAMPLE, tariff_type="spot_hourly")
    assert [item["id"] for item in result] == ["at_spot", "de_spot"]


def test_filter_combined() -> None:
    result = filter_tariffs(_SAMPLE, land="AT", tariff_type="fixed_cent")
    assert [item["id"] for item in result] == ["at_fix"]


def test_filter_all_keeps_missing_land() -> None:
    result = filter_tariffs(_SAMPLE)
    assert len(result) == 4
    assert "legacy" in {item["id"] for item in result}


def test_filter_land_excludes_missing_land() -> None:
    result = filter_tariffs(_SAMPLE, land="AT")
    assert "legacy" not in {item["id"] for item in result}


def test_lands_and_types_present() -> None:
    assert lands_present(_SAMPLE) == ["AT", "DE"]
    assert types_present(_SAMPLE) == ["fixed", "fixed_cent", "spot_hourly"]


def test_types_present_after_land_cascade() -> None:
    after_land = filter_tariffs(_SAMPLE, land="DE")
    assert types_present(after_land) == ["spot_hourly"]


def test_with_current_inside_filters() -> None:
    filtered = filter_tariffs(_SAMPLE, land="AT")
    result, outside = with_current_tariff(filtered, _SAMPLE, "at_spot")
    assert outside is False
    assert [item["id"] for item in result] == ["at_spot", "at_fix"]


def test_with_current_outside_filters_unions() -> None:
    filtered = filter_tariffs(_SAMPLE, land="DE")
    result, outside = with_current_tariff(filtered, _SAMPLE, "at_spot")
    assert outside is True
    assert [item["id"] for item in result] == ["at_spot", "de_spot"]


def test_with_current_unknown_id() -> None:
    filtered = filter_tariffs(_SAMPLE, land="DE")
    result, outside = with_current_tariff(filtered, _SAMPLE, "missing")
    assert outside is False
    assert [item["id"] for item in result] == ["de_spot"]
