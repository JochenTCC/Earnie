"""SOC-Min-Immediate (ASAP EV floor via get_evcs_soc_min_immediate)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer.charging_context import (
    asap_indices_for_urgent_min,
    urgent_min_kwh_from_soc,
)
from optimizer.eauto_milp import _preset_must_charge_now
from optimizer.milp import milp_horizon_schedule
from settings import ehal_marker_resolve as resolve
from ui.ehal_loxone_mapping import EV_FIELDS

_REPO = Path(__file__).resolve().parents[1]


def _ev_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "battery_capacity_kwh": 50.0,
        "ehal_bindings": {
            "get_evcs_soc_min_immediate": "Earnie_EAuto_SOCMinSofort",
            "set_evcs_max_current": "Earnie_EAuto_Soll_A",
        },
        "charging_schedule": {
            "enabled": True,
            "target_soc_percent": 80.0,
            "charging_efficiency": 1.0,
            "milp": {
                "live_modus_a_min_remaining_kwh": 2.8,
                "tie_break_on_epsilon": 0.001,
                "tie_break_time_epsilon": 0.0001,
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


class TestResolveSocMinImmediate:
    def test_absent_binding_inactive(self):
        consumer = {"id": "ev", "charging_schedule": {"target_soc_percent": 80.0}}
        assert resolve.resolve_get_evcs_soc_min_immediate(consumer) is None

    def test_zero_or_negative_inactive(self):
        consumer = _ev_consumer()
        with patch(
            "integrations.loxone_client.fetch_loxone_generic_value",
            return_value=0.0,
        ):
            assert resolve.resolve_get_evcs_soc_min_immediate(consumer) is None
        with patch(
            "integrations.loxone_client.fetch_loxone_generic_value",
            return_value=-5.0,
        ):
            assert resolve.resolve_get_evcs_soc_min_immediate(consumer) is None

    def test_clamps_to_limit_soc(self):
        consumer = _ev_consumer()
        with patch(
            "integrations.loxone_client.fetch_loxone_generic_value",
            return_value=90.0,
        ), patch.object(resolve, "resolve_get_evcs_limit_soc", return_value=80.0):
            assert resolve.resolve_get_evcs_soc_min_immediate(consumer) == 80.0

    def test_below_limit_passthrough(self):
        consumer = _ev_consumer()
        with patch(
            "integrations.loxone_client.fetch_loxone_generic_value",
            return_value=50.0,
        ), patch.object(resolve, "resolve_get_evcs_limit_soc", return_value=80.0):
            assert resolve.resolve_get_evcs_soc_min_immediate(consumer) == 50.0


class TestUrgentMinHelpers:
    def test_urgent_min_kwh_from_soc(self):
        consumer = _ev_consumer()
        energy = urgent_min_kwh_from_soc(
            consumer,
            actual_soc=20.0,
            soc_min_immediate=40.0,
            capacity_kwh=50.0,
        )
        assert energy == pytest.approx(10.0)

    def test_urgent_min_zero_when_already_above(self):
        consumer = _ev_consumer()
        assert (
            urgent_min_kwh_from_soc(
                consumer,
                actual_soc=50.0,
                soc_min_immediate=40.0,
                capacity_kwh=50.0,
            )
            == 0.0
        )

    def test_asap_indices_cover_hours_needed(self):
        start = datetime(2026, 6, 28, 9, 0)
        matrix = [
            {
                "slot_datetime": start + timedelta(hours=i),
                "hour": (start + timedelta(hours=i)).hour,
            }
            for i in range(12)
        ]
        asap = asap_indices_for_urgent_min(
            matrix, horizon=12, urgent_min_kwh=7.0, max_kw=3.5
        )
        assert asap == [0, 1, 2]


class TestPresetMustCharge:
    def test_urgent_min_forces_must_charge_now(self):
        consumer = _ev_consumer()
        start = datetime(2026, 6, 28, 9, 0)
        matrix = [
            {
                "slot_datetime": start + timedelta(hours=i),
                "hour": (start + timedelta(hours=i)).hour,
                "k_act": 50.0 if i < 5 else 5.0,
            }
            for i in range(10)
        ]
        assert (
            _preset_must_charge_now(
                matrix,
                consumer,
                remaining_kwh=20.0,
                schedule_indices=list(range(10)),
                charging_context={"urgent_min_kwh": 7.0},
            )
            is True
        )


class TestMilpAsapFloor:
    def test_plan_puts_urgent_min_in_early_expensive_slots(self):
        start = datetime(2026, 6, 28, 9, 0)
        deadline = start + timedelta(hours=18)
        matrix = []
        for i in range(18):
            dt = start + timedelta(hours=i)
            matrix.append(
                {
                    "slot_datetime": dt,
                    "hour": dt.hour,
                    "date": dt.date(),
                    "expected_p_pv": 0.2,
                    "expected_p_act": 0.5,
                    "k_act": 40.0 if i < 6 else 5.0,
                }
            )
        urgent_min = 7.0
        consumer = _ev_consumer()
        schedule = milp_horizon_schedule(
            matrix,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[consumer],
            consumer_remaining_kwh={"eauto": 20.0},
            charging_contexts={
                "eauto": {
                    "active": True,
                    "plugged_in": True,
                    "deadline": deadline,
                    "target_kwh": 20.0,
                    "use_time_window": False,
                    "urgent_min_kwh": urgent_min,
                    "soc_min_immediate": 40.0,
                }
            },
            flex_indices=list(range(len(matrix))),
        )
        asap = asap_indices_for_urgent_min(
            matrix,
            horizon=len(matrix),
            urgent_min_kwh=urgent_min,
            max_kw=3.5,
            deadline=deadline,
        )
        planned_asap = sum(
            float(schedule[t]["consumer_powers"].get("eauto", 0.0)) for t in asap
        )
        assert planned_asap >= urgent_min - 0.15


class TestChargingContextEnrichment:
    def test_plugged_in_sets_urgent_min_kwh(self):
        from optimizer import charging_context as cc

        consumer = _ev_consumer()
        consumer["ehal_bindings"]["sens_evcs_connected"] = "EV_Plug"
        consumer["ehal_bindings"]["sens_evcs_soc_act"] = "EV_SOC"
        horizon = datetime(2026, 6, 28, 12, 0)
        with patch.object(
            cc, "resolve_get_evcs_soc_min_immediate", return_value=40.0
        ), patch.object(
            cc, "resolve_get_evcs_limit_soc", return_value=80.0
        ), patch.object(
            cc.loxone_client, "fetch_loxone_generic_value", return_value=1.0
        ), patch.object(
            cc, "fetch_loxone_actual_soc_percent", return_value=20.0
        ), patch.object(
            cc.loxone_client,
            "resolve_consumer_battery_capacity_kwh",
            return_value=50.0,
        ), patch.object(
            cc, "loxone_reports_charge_complete", return_value=False
        ), patch.object(cc, "_loxone_ready_raw", return_value=None):
            ctx = cc.fetch_loxone_charging_context(consumer, horizon)
        assert ctx["soc_min_immediate"] == 40.0
        assert ctx["urgent_min_kwh"] == pytest.approx(10.0)
        assert ctx["target_kwh"] == pytest.approx(30.0)


class TestMappingCatalog:
    def test_ev_fields_and_greenfield(self):
        assert "get_evcs_soc_min_immediate" in EV_FIELDS
        greenfield = json.loads(
            (_REPO / "share" / "loxone" / "greenfield_device_map.json").read_text(
                encoding="utf-8"
            )
        )
        rows = [
            r
            for r in greenfield.get("markers", [])
            if isinstance(r, dict)
            and r.get("ehal_field") == "get_evcs_soc_min_immediate"
        ]
        assert any(r.get("name") == "Earnie_EAuto_SOCMinSofort" for r in rows)
        vo = (
            _REPO / "share" / "loxone" / "templates" / "VirtualOut" / "VO_Earnie_EV.xml"
        ).read_text(encoding="utf-8")
        assert "Earnie_EAuto_SOCMinSofort" in vo
        assert "get_evcs_soc_min_immediate" in vo
