"""Tests für E-Auto Sofort-Laden (charge_immediate)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from optimizer import charge_immediate as ci


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "daily_target_source": "loxone",
        "charging_schedule": {
            "enabled": True,
            "battery_capacity_kwh": 16.0,
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.9,
            "loxone": {
                "plugged_in_name": "Ernie_EAuto_Da",
                "charge_immediate_name": "E-Auto_SOFORT_LADEN",
            },
        },
    }


def _plugged_context(*, target_kwh: float = 10.0) -> dict:
    return {
        "active": True,
        "plugged_in": True,
        "target_kwh": target_kwh,
        "use_time_window": False,
        "source_label": "loxone (angeschlossen)",
    }


class TestImmediateChargingActive:
    def test_inactive_when_switch_off(self):
        consumer = _eauto_consumer()
        ctx = _plugged_context()
        assert not ci.is_immediate_charging_active(
            consumer, ctx, switch_on=False, live_kw=3.5
        )

    def test_inactive_when_not_plugged_in(self):
        consumer = _eauto_consumer()
        ctx = {**_plugged_context(), "plugged_in": False}
        assert not ci.is_immediate_charging_active(
            consumer, ctx, switch_on=True, live_kw=3.5
        )

    def test_active_when_switch_on_and_charging(self):
        consumer = _eauto_consumer()
        ctx = _plugged_context()
        assert ci.is_immediate_charging_active(
            consumer, ctx, switch_on=True, live_kw=3.2
        )

    def test_active_when_switch_on_and_remaining_target(self):
        consumer = _eauto_consumer()
        ctx = _plugged_context(target_kwh=8.0)
        assert ci.is_immediate_charging_active(
            consumer, ctx, switch_on=True, live_kw=0.0
        )

    def test_inactive_when_done_charging(self):
        consumer = _eauto_consumer()
        ctx = {**_plugged_context(), "target_kwh": 0.0}
        assert not ci.is_immediate_charging_active(
            consumer, ctx, switch_on=True, live_kw=0.0
        )


class TestImmediateHorizon:
    def test_planning_horizon_is_six_hours(self):
        assert ci.immediate_horizon_hours(10.0, 3.5, 24, consumer_id="eauto") == 6
        assert ci.immediate_horizon_hours(0.0, 3.5, 24, consumer_id="eauto") == 6
        assert ci.immediate_horizon_hours(10.0, 3.5, 4, consumer_id="eauto") == 4


class TestImmediateMatrix:
    def test_moves_live_flex_into_baseload(self):
        start = datetime(2026, 6, 27, 14, 0)
        matrix = [
            {
                "slot_datetime": start + timedelta(hours=i),
                "expected_p_act": 1.0 if i == 0 else 0.8,
                "expected_flex_kw": {"eauto": 3.5 if i == 0 else 0.0, "swimspa": 0.0},
            }
            for i in range(4)
        ]
        contexts = {
            "eauto": {
                "immediate_charge": True,
                "immediate_charge_kw": 3.5,
                "immediate_charge_current_kw": 3.5,
                "immediate_horizon_hours": 2,
            }
        }
        updated = ci.apply_immediate_charge_to_matrix(
            matrix, contexts, [_eauto_consumer()]
        )
        assert updated[0]["expected_p_act"] == pytest.approx(4.5)
        assert updated[0]["expected_flex_kw"] == {"swimspa": 0.0}
        assert updated[1]["expected_p_act"] == pytest.approx(4.3)
        assert updated[2]["expected_p_act"] == pytest.approx(0.8)


class TestPrepareOptimizationMatrix:
    def test_prepare_applies_immediate_charge_to_matrix(self):
        consumer = _eauto_consumer()
        start = datetime(2026, 6, 27, 14, 0)
        matrix = [
            {
                "slot_datetime": start,
                "consumption_mode": "live_snapshot",
                "expected_p_act": 1.0,
                "expected_flex_kw": {"eauto": 3.5},
            }
        ]
        base_ctx = _plugged_context()
        with patch(
            "optimizer.charging_context.resolve_charging_contexts",
            return_value={
                "eauto": {
                    **base_ctx,
                    "immediate_charge": True,
                    "immediate_charge_kw": 3.5,
                    "immediate_charge_current_kw": 3.5,
                    "immediate_horizon_hours": 2,
                }
            },
        ):
            prepared, contexts, _ = ci.prepare_optimization_matrix(
                matrix,
                {"eauto": 10.0},
                consumers=[consumer],
            )
        assert contexts["eauto"]["immediate_charge"] is True
        assert prepared[0]["expected_p_act"] == pytest.approx(4.5)
        assert prepared[0]["expected_flex_kw"] == {}


class TestMainStateFallback:
    def test_merge_labels_from_event_trigger_snapshot(self):
        main_state = {
            "event_trigger_snapshot": {
                "eauto_charge_immediate": True,
                "eauto_plugged_in": True,
            },
            "flex_live_kw": {"eauto": 3.479},
            "charging_contexts": {
                "eauto": {
                    "active": True,
                    "plugged_in": True,
                    "target_kwh": 11.5,
                }
            },
        }
        labels = ci.merge_immediate_charging_labels({}, main_state)
        assert labels == ["eauto: 3.479 kW live (Sofort-Laden)"]


class TestChartDisplay:
    def test_apply_immediate_charge_chart_display_splits_baseload(self):
        consumer = _eauto_consumer()
        chart_row = {
            "Verbrauch-Prognose (kW)": 8.0,
            "PV-Prognose (kW)": 2.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 6.0,
            "E-Auto (kW)": 0.0,
        }
        contexts = {
            "eauto": {
                "immediate_charge": True,
                "immediate_charge_kw": 3.5,
                "immediate_charge_current_kw": 3.5,
                "immediate_horizon_hours": 3,
            }
        }
        ci.apply_immediate_charge_chart_display(chart_row, 0, contexts)
        assert chart_row["E-Auto (kW)"] == 3.5
        assert chart_row["E-Auto sofort_laden"] == 1
        assert chart_row["Verbrauch-Prognose (kW)"] == pytest.approx(4.5)
        assert chart_row["Netzbezug (kW)"] == pytest.approx(6.0)


class TestEnrichContext:
    def test_enrich_sets_skip_loxone_output(self):
        consumer = _eauto_consumer()
        with patch.object(ci, "fetch_charge_immediate_switch", return_value=True):
            result = ci.enrich_context_with_immediate_charge(
                consumer,
                _plugged_context(),
                live_kw=3.5,
                horizon=24,
            )
        assert result["immediate_charge"] is True
        assert result["active"] is False
        assert result["skip_loxone_output"] is True
        assert result["immediate_charge_kw"] == 3.5

    def test_enrich_unchanged_without_io_name(self):
        consumer = _eauto_consumer()
        consumer["charging_schedule"]["loxone"].pop("charge_immediate_name")
        base = _plugged_context()
        assert (
            ci.enrich_context_with_immediate_charge(
                consumer, base, live_kw=3.5, horizon=24
            )
            is base
        )
