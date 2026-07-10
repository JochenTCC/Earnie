"""Tests für Ladekontext und Abwesenheits-Prognose (charging_schedule)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from optimizer import charging_context as cc


def _eauto_consumer(*, forecast_when_absent: bool = True) -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "daily_target_source": "loxone",
        "charging_schedule": {
            "enabled": True,
            "forecast_when_absent": forecast_when_absent,
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.90,
            "weekday": {
                "car_available_from_hour": 19,
                "ready_by_hour": 7,
                "daily_rest_soc": 20.0,
            },
            "weekend": {
                "car_available_from_hour": 18,
                "ready_by_hour": 10,
                "daily_rest_soc": 40.0,
            },
            "loxone": {
                "plugged_in_name": "Ernie_EAuto_Da",
                "ready_by_time_name": "Ernie_EAuto_FertigUm",
                "soc_at_plug_in_name": "Rest-SOC",
                "battery_capacity_kwh_name": "Batteriekapazität_E-Auto",
            },
        },
    }


def _patch_eauto_capacity():
    return patch.object(
        cc.loxone_client, "resolve_consumer_battery_capacity_kwh", return_value=16.0
    )


def _hour_matrix(start: datetime, hours: int = 24) -> list:
    return [
        {
            "slot_datetime": start + timedelta(hours=i),
            "hour": (start + timedelta(hours=i)).hour,
        }
        for i in range(hours)
    ]


class TestAbsentAvailability:
  def test_next_scheduled_weekday_before_arrival(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 22, 17, 0)  # Montag
      assert cc.next_scheduled_availability(horizon, consumer) == datetime(2026, 6, 22, 19, 0)

  def test_resolve_absent_same_day_past_slot_uses_next_scheduled(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 22, 21, 0)
      assert cc.resolve_absent_availability(horizon, consumer) == cc.next_scheduled_availability(
          horizon, consumer
      )

  def test_resolve_absent_overnight_window_still_returns_horizon(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 23, 8, 0)  # Dienstag, Fenster von Montag noch offen
      assert cc.resolve_absent_availability(horizon, consumer) == horizon

  def test_resolve_absent_with_timezone_aware_horizon(self):
      from zoneinfo import ZoneInfo

      consumer = _eauto_consumer()
      tz = ZoneInfo("Europe/Vienna")
      horizon = datetime(2026, 6, 23, 8, 0, tzinfo=tz)
      result = cc.resolve_absent_availability(horizon, consumer)
      assert result == horizon
      assert result.tzinfo == tz

  def test_charging_deadline_after_weekday_arrival(self):
      consumer = _eauto_consumer()
      arrival = datetime(2026, 6, 22, 19, 0)
      assert cc.charging_deadline_after(arrival, consumer) == datetime(2026, 6, 23, 7, 0)


class TestLoxoneAbsentForecast:
  def test_forecast_inactive_without_loxone_deadline(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 22, 17, 0)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), patch.object(
          cc.loxone_client, "fetch_loxone_raw_value", return_value=None
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is False
      assert ctx["target_kwh"] == 0.0
      assert "keine aktive Fertigstellungszeit" in ctx["source_label"]

  def test_forecast_inactive_with_empty_loxone_deadline(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 22, 17, 0)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), patch.object(
          cc.loxone_client, "fetch_loxone_raw_value", return_value=""
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is False
      assert ctx["target_kwh"] == 0.0

  def test_forecast_uses_loxone_fertig_um_when_absent(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 22, 17, 0)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), patch.object(
          cc.loxone_client, "fetch_loxone_raw_value", return_value="Morgen, 16:03"
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is True
      assert ctx["anticipated"] is True
      assert ctx["plugged_in"] is False
      assert ctx["available_from"] == datetime(2026, 6, 22, 19, 0)
      assert ctx["deadline"] == datetime(2026, 6, 23, 16, 3)
      assert ctx["use_time_window"] is False
      assert "FertigUm Loxone" in ctx["source_label"]

  def test_forecast_timezone_aware_horizon(self):
      from zoneinfo import ZoneInfo

      consumer = _eauto_consumer()
      tz = ZoneInfo("Europe/Vienna")
      horizon = datetime(2026, 6, 22, 17, 0, tzinfo=tz)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), patch.object(
          cc.loxone_client, "fetch_loxone_raw_value", return_value="Morgen, 16:03"
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is True
      assert ctx["available_from"] == datetime(2026, 6, 22, 19, 0, tzinfo=tz)
      assert ctx["deadline"] == datetime(2026, 6, 23, 16, 3, tzinfo=tz)

  def test_late_return_with_loxone_fertig_um(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 23, 8, 0)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), patch.object(
          cc.loxone_client, "fetch_loxone_raw_value", return_value="Heute, 16:03"
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is True
      assert ctx["available_from"] == horizon
      assert ctx["deadline"] == datetime(2026, 6, 23, 16, 3)
      assert ctx["use_time_window"] is False

  def test_forecast_same_day_past_slot_waits_for_next_arrival(self):
      consumer = _eauto_consumer()
      consumer["charging_schedule"]["weekday"]["car_available_from_hour"] = 11
      consumer["charging_schedule"]["weekend"]["car_available_from_hour"] = 10
      horizon = datetime(2026, 7, 10, 11, 15)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), patch.object(
          cc.loxone_client, "fetch_loxone_raw_value", return_value="Morgen, 12:00"
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is True
      assert ctx["anticipated"] is True
      assert ctx["available_from"] == datetime(2026, 7, 11, 10, 0)

  def test_forecast_disabled_when_unplugged(self):
      consumer = _eauto_consumer(forecast_when_absent=False)
      horizon = datetime(2026, 6, 22, 17, 0)
      with patch.object(
          cc.loxone_client, "fetch_loxone_generic_value", return_value=0
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is False
      assert ctx["target_kwh"] == 0.0
      assert ctx["source_label"] == "loxone (nicht angeschlossen)"

  def test_plugged_in_unchanged(self):
      consumer = _eauto_consumer()
      horizon = datetime(2026, 6, 22, 17, 0)
      with patch.object(
          cc.loxone_client,
          "fetch_loxone_generic_value",
          side_effect=[1, 50.0],
      ), patch.object(
          cc.loxone_client,
          "fetch_loxone_raw_value",
          return_value="Morgen, 07:00",
      ), _patch_eauto_capacity():
          ctx = cc.fetch_loxone_charging_context(consumer, horizon)

      assert ctx["active"] is True
      assert ctx["plugged_in"] is True
      assert ctx.get("anticipated") is None
      assert ctx["use_time_window"] is False
      assert "angeschlossen" in ctx["source_label"]


class TestEligibleIndices:
  def test_absent_forecast_blocks_hours_before_arrival(self):
      consumer = _eauto_consumer()
      start = datetime(2026, 6, 22, 17, 0)
      matrix = _hour_matrix(start, 24)
      ctx = {
          "active": True,
          "anticipated": True,
          "available_from": datetime(2026, 6, 22, 19, 0),
          "deadline": datetime(2026, 6, 23, 7, 0),
          "use_time_window": True,
      }
      eligible = cc.consumer_charging_eligible_indices(
          matrix, consumer, list(range(24)), ctx
      )
      eligible_hours = [matrix[i]["slot_datetime"].hour for i in eligible]
      assert 17 not in eligible_hours
      assert 18 not in eligible_hours
      assert 19 in eligible_hours
      assert 23 in eligible_hours
      assert 0 in eligible_hours
      assert 6 in eligible_hours
      assert 7 not in eligible_hours

  def test_late_return_eligible_from_current_hour(self):
      consumer = _eauto_consumer()
      start = datetime(2026, 6, 22, 21, 0)
      matrix = _hour_matrix(start, 6)
      ctx = {
          "active": True,
          "anticipated": True,
          "available_from": start,
          "deadline": datetime(2026, 6, 23, 7, 0),
          "use_time_window": True,
      }
      eligible = cc.consumer_charging_eligible_indices(
          matrix, consumer, list(range(6)), ctx
      )
      assert eligible[0] == 0
      assert len(eligible) == 6

  def test_fertig_um_deadline_allows_midday_hours(self):
      consumer = _eauto_consumer()
      start = datetime(2026, 6, 22, 19, 0)
      matrix = _hour_matrix(start, 24)
      ctx = {
          "active": True,
          "anticipated": True,
          "available_from": datetime(2026, 6, 22, 19, 0),
          "deadline": datetime(2026, 6, 23, 16, 3),
          "use_time_window": False,
      }
      eligible = cc.consumer_charging_eligible_indices(
          matrix, consumer, list(range(24)), ctx
      )
      eligible_hours = [matrix[i]["slot_datetime"].hour for i in eligible]
      assert 10 in eligible_hours
      assert 14 in eligible_hours
      assert 15 in eligible_hours
      assert not any(
          matrix[i]["slot_datetime"] >= datetime(2026, 6, 23, 16, 3) for i in eligible
      )
