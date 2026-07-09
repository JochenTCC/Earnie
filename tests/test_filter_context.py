"""Tests für natives SwimSpa-Filterfenster (filter_context, Phase 2)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer import filter_context as fc
from optimizer.milp import milp_optimizer


def _swimspa_filter() -> dict:
    return {
        "id": "swimspa_filter",
        "name": "SwimSpa Filter",
        "nominal_power_kw": 0.18,
        "min_on_quarterhours": 4,
        "signal_type": "binary",
        "daily_target_source": "loxone_remaining_hours",
        "filter_schedule": {
            "enabled": True,
            "config_fallback": {
                "native_start_hour": 10,
                "native_duration_hours": 4.0,
            },
        },
    }


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
    }


def _matrix_24h(day: datetime | None = None) -> list[dict]:
    start = day or datetime(2026, 7, 7, 0, 0)
    matrix: list[dict] = []
    for i in range(24):
        dt = start + timedelta(hours=i)
        matrix.append(
            {
                "hour": dt.hour,
                "date": dt.date(),
                "slot_datetime": dt,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.3,
                "k_act": 15.0 if 10 <= dt.hour < 14 else 2.0,
                "consumption_mode": "logged_day",
            }
        )
    return matrix


class TestSlotInNativeWindow:
    def test_inside_same_day_window(self):
        slot = datetime(2026, 7, 7, 11, 0)
        assert fc.slot_in_native_window(slot, 10, 4.0)

    def test_outside_same_day_window(self):
        slot = datetime(2026, 7, 7, 9, 0)
        assert not fc.slot_in_native_window(slot, 10, 4.0)

    def test_spans_midnight_from_previous_day(self):
        slot = datetime(2026, 7, 8, 1, 0)
        assert fc.slot_in_native_window(slot, 22, 4.0)

    def test_window_end_is_exclusive(self):
        slot = datetime(2026, 7, 7, 14, 0)
        assert not fc.slot_in_native_window(slot, 10, 4.0)

    def test_aware_slot_in_planning_timezone(self):
        from zoneinfo import ZoneInfo

        slot = datetime(2026, 7, 7, 11, 0, tzinfo=ZoneInfo("Europe/Vienna"))
        assert fc.slot_in_native_window(slot, 10, 4.0)


class TestNativeBlockedIndices:
    def test_blocks_native_hours_only(self):
        matrix = _matrix_24h()
        blocked = fc.native_blocked_indices(matrix, list(range(24)), 10, 4.0)
        assert blocked == [10, 11, 12, 13]

    def test_resolve_filter_context_uses_config_fallback(self):
        matrix = _matrix_24h()
        ctx = fc.resolve_filter_context(_swimspa_filter(), matrix, logged_simulation=True)
        assert ctx["blocked_indices"] == [10, 11, 12, 13]
        assert ctx["source_label"] == "config_fallback"


class TestErnieFilterRemaining:
    def test_native_covers_debt_fully(self):
        consumer = _swimspa_filter()
        matrix = _matrix_24h()
        ctx = fc.resolve_filter_context(consumer, matrix, logged_simulation=True)
        assert fc.expected_native_delivery_kwh(consumer, ctx) == pytest.approx(0.72)
        assert fc.ernie_filter_remaining_kwh(consumer, 0.63, ctx) == pytest.approx(0.0)

    def test_native_partial_credit(self):
        consumer = _swimspa_filter()
        matrix = _matrix_24h()
        ctx = fc.resolve_filter_context(consumer, matrix, logged_simulation=True)
        assert fc.ernie_filter_remaining_kwh(consumer, 1.0, ctx) == pytest.approx(0.28)

    def test_no_filter_context_returns_debt(self):
        consumer = _swimspa_filter()
        assert fc.ernie_filter_remaining_kwh(consumer, 0.63, None) == pytest.approx(0.63)


class TestMilpFilterWindow:
    def test_plans_outside_native_window(self):
        matrix = _matrix_24h()
        consumer = _swimspa_filter()
        filter_ctx = fc.resolve_filter_context(consumer, matrix, logged_simulation=True)
        ernie_rem = fc.ernie_filter_remaining_kwh(consumer, 1.0, filter_ctx)
        _, _, _, powers, _, _, _ = milp_optimizer(
            matrix,
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[consumer],
            consumer_remaining_kwh={"swimspa_filter": ernie_rem},
            filter_contexts={"swimspa_filter": filter_ctx},
        )
        assert powers.get("swimspa_filter", 0.0) == pytest.approx(0.18)
        blocked = set(filter_ctx["blocked_indices"])
        for hour_idx, row in enumerate(matrix):
            if hour_idx in blocked:
                continue
            if row["k_act"] <= 2.01:
                break
        else:
            pytest.fail("kein günstiger Slot außerhalb des nativen Fensters")

    def test_no_ernie_when_native_covers_debt(self):
        matrix = _matrix_24h()
        consumer = _swimspa_filter()
        filter_ctx = fc.resolve_filter_context(consumer, matrix, logged_simulation=True)
        ernie_rem = fc.ernie_filter_remaining_kwh(consumer, 0.63, filter_ctx)
        assert ernie_rem == pytest.approx(0.0)
        _, _, _, powers, _, _, _ = milp_optimizer(
            matrix,
            current_hour=8,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[consumer],
            consumer_remaining_kwh={"swimspa_filter": ernie_rem},
            filter_contexts={"swimspa_filter": filter_ctx},
        )
        assert powers.get("swimspa_filter", 0.0) == pytest.approx(0.0)

    def test_no_power_in_blocked_native_slots(self):
        matrix = _matrix_24h()
        consumer = _swimspa_filter()
        filter_ctx = fc.resolve_filter_context(consumer, matrix, logged_simulation=True)
        ernie_rem = fc.ernie_filter_remaining_kwh(consumer, 1.0, filter_ctx)
        powers_by_hour: dict[int, float] = {}
        for hour in range(24):
            slice_matrix = matrix[hour:]
            _, _, _, powers, _, _, _ = milp_optimizer(
                slice_matrix,
                current_hour=matrix[hour]["hour"],
                current_soc=50.0,
                battery_params=_battery_params(),
                k_push=3.5,
                verbose=False,
                consumers=[consumer],
                consumer_remaining_kwh={"swimspa_filter": ernie_rem},
                filter_contexts={
                    "swimspa_filter": fc.resolve_filter_context(
                        consumer,
                        slice_matrix,
                        logged_simulation=True,
                    )
                },
            )
            powers_by_hour[hour] = powers.get("swimspa_filter", 0.0)

        for blocked_hour in filter_ctx["blocked_indices"]:
            assert powers_by_hour[blocked_hour] == pytest.approx(0.0)


def _swimspa_filter_loxone() -> dict:
    consumer = _swimspa_filter()
    consumer["filter_schedule"] = {
        "enabled": True,
        "loxone": {
            "native_start_hour_name": "FilterStart",
            "native_duration_hours_name": "FilterDuration",
        },
        "config_fallback": {
            "native_start_hour": 10,
            "native_duration_hours": 4.0,
        },
    }
    return consumer


def _matrix_forecast_6h() -> list[dict]:
    start = datetime(2026, 7, 7, 8, 0)
    return [
        {
            "hour": (start + timedelta(hours=i)).hour,
            "date": start.date(),
            "slot_datetime": start + timedelta(hours=i),
            "expected_p_pv": 0.0,
            "expected_p_act": 0.3,
            "k_act": 2.0,
            "consumption_mode": "forecast",
        }
        for i in range(6)
    ]


class TestFilterContextCaching:
    def test_simulate_horizon_resolves_native_window_once(self, monkeypatch):
        from integrations import loxone_client
        from optimizer.simulation import simulate_horizon

        fetch_calls: list[str] = []

        def _mock_start(name: str):
            fetch_calls.append(name)
            return 10.0, "integer", "10 h"

        monkeypatch.setattr(
            loxone_client, "fetch_filter_native_start_hour", _mock_start
        )
        monkeypatch.setattr(
            loxone_client, "fetch_loxone_generic_value", lambda _name: 4.0
        )

        matrix = _matrix_forecast_6h()
        consumer = _swimspa_filter_loxone()
        simulate_horizon(
            matrix,
            50.0,
            verbose=False,
            matrix_prepared=True,
            charging_contexts={},
            consumer_daily_targets_kwh={"swimspa_filter": 0.0},
            flexible_consumers=[consumer],
        )
        assert fetch_calls == ["FilterStart"]

    def test_simulate_horizon_reuses_passed_filter_contexts(self, monkeypatch):
        from integrations import loxone_client
        from optimizer.simulation import simulate_horizon

        fetch_calls: list[str] = []

        def _mock_start(name: str):
            fetch_calls.append(name)
            return 10.0, "integer", "10 h"

        monkeypatch.setattr(
            loxone_client, "fetch_filter_native_start_hour", _mock_start
        )
        monkeypatch.setattr(
            loxone_client, "fetch_loxone_generic_value", lambda _name: 4.0
        )

        matrix = _matrix_forecast_6h()
        consumer = _swimspa_filter_loxone()
        filters = fc.resolve_filter_contexts(matrix, [consumer])
        fetch_calls.clear()

        simulate_horizon(
            matrix,
            50.0,
            verbose=False,
            matrix_prepared=True,
            charging_contexts={},
            consumer_daily_targets_kwh={"swimspa_filter": 0.0},
            flexible_consumers=[consumer],
            filter_contexts=filters,
        )
        assert fetch_calls == []
