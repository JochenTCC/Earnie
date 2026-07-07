"""Tests für daily_target_source=loxone_remaining_hours (SwimSpa Filter, Phase 1)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from data import consumer_targets
import optimizer


def _swimspa_filter() -> dict:
    return {
        "id": "swimspa_filter",
        "name": "SwimSpa Filter",
        "nominal_power_kw": 0.18,
        "daily_target_kwh": 0.36,
        "daily_target_source": "loxone_remaining_hours",
        "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
    }


@patch("integrations.loxone_client.fetch_loxone_generic_value")
def test_resolve_loxone_remaining_hours_from_sollstunden(mock_fetch):
    mock_fetch.return_value = 5.0
    today = date.today()
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa_filter(),
        today,
        None,
        {},
    )
    assert result == pytest.approx(5.0 * 0.18)
    mock_fetch.assert_called_once_with("Ernie_Swimspa_Filter_Sollstunden")


@patch("integrations.loxone_client.fetch_loxone_generic_value")
def test_resolve_loxone_remaining_hours_zero_is_inactive(mock_fetch):
    mock_fetch.return_value = 0.0
    today = date.today()
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa_filter(),
        today,
        None,
        {},
    )
    assert result == 0.0


@patch("integrations.loxone_client.fetch_loxone_generic_value")
def test_resolve_loxone_remaining_hours_missing_marker_is_inactive(mock_fetch):
    mock_fetch.return_value = None
    today = date.today()
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa_filter(),
        today,
        None,
        {},
    )
    assert result == 0.0


@patch("data.consumer_targets._historical_totals_for_date")
def test_resolve_loxone_remaining_hours_uses_historical_totals_for_other_dates(mock_totals):
    mock_totals.return_value = {"swimspa_filter": 0.72}
    other_day = date(2020, 1, 1)
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa_filter(),
        other_day,
        None,
        {},
    )
    assert result == 0.72
    mock_totals.assert_called_once()


@patch("data.consumer_targets._historical_totals_for_date")
def test_resolve_loxone_remaining_hours_falls_back_to_config_kwh(mock_totals):
    mock_totals.return_value = {}
    other_day = date(2020, 1, 1)
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa_filter(),
        other_day,
        None,
        {},
    )
    assert result == 0.36


@patch("optimizer._load_consumer_state")
@patch("data.consumer_targets.resolve_consumer_daily_targets")
def test_get_consumer_remaining_kwh_skips_delivered(mock_targets, mock_state):
    mock_targets.return_value = {"swimspa_filter": 0.9}
    mock_state.return_value = {
        "date": date.today().isoformat(),
        "delivered": {"swimspa_filter": 0.36},
        "charging_sessions": {},
    }
    remaining = optimizer.get_consumer_remaining_kwh(
        consumers=[_swimspa_filter()],
        consumer_daily_targets_kwh={"swimspa_filter": 0.9},
    )
    assert remaining["swimspa_filter"] == pytest.approx(0.9)


@patch("optimizer._load_consumer_state")
@patch("data.consumer_targets.resolve_consumer_daily_targets")
def test_get_consumer_remaining_kwh_still_subtracts_delivered_for_others(
    mock_targets, mock_state
):
    swimspa = {
        "id": "swimspa",
        "daily_target_source": "config",
        "daily_target_kwh": 8.0,
        "nominal_power_kw": 2.8,
    }
    mock_targets.return_value = {"swimspa": 8.0}
    mock_state.return_value = {
        "date": date.today().isoformat(),
        "delivered": {"swimspa": 2.0},
        "charging_sessions": {},
    }
    remaining = optimizer.get_consumer_remaining_kwh(
        consumers=[swimspa],
        consumer_daily_targets_kwh={"swimspa": 8.0},
    )
    assert remaining["swimspa"] == pytest.approx(6.0)
