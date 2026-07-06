"""Regressionstests gegen archivierte Produktiv-Dumps."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer import charging_context as cc
from optimizer import charging_session as cs
from optimizer import delivery_tracking as dt
from tests.fixtures import prod_dump_fixtures as pdf

CASE_EAUTO = "eauto_deadline_missed_2026-06-27"
CASE_URGENT = "eauto_urgent_deferred_cheap_hours_2026-06-28"
CASE_FALSE_COMPLETE = "eauto_false_complete_2026-06-29"
ALL_CASES = (CASE_EAUTO, CASE_URGENT, CASE_FALSE_COMPLETE)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value)[:19])


def _integrate_kw(rows: list[dict], start: datetime, end: datetime, key: str) -> float:
    total = 0.0
    for row in rows:
        ts = _parse_ts(row["written_at"])
        if not (start <= ts <= end):
            continue
        kw = float((row.get(key) or {}).get("eauto", 0) or 0)
        total += kw * 0.25
    return round(total, 2)


def _hour_from_row(row: dict) -> int:
    return int(str(row["Uhrzeit"]).split(":")[0])


def _matrix_from_debug_rows(rows: list[dict], session_date: str) -> list[dict]:
    base = datetime.fromisoformat(f"{session_date}T09:00:00")
    matrix: list[dict] = []
    for index, row in enumerate(rows):
        slot = base + timedelta(hours=index)
        matrix.append(
            {
                "slot_datetime": slot,
                "hour": slot.hour,
                "date": slot.date(),
                "expected_p_pv": float(row["PV-Prognose (kW)"]),
                "expected_p_act": float(row["Verbrauch-Prognose (kW)"]),
                "k_act": float(row["Strompreis (Cent/kWh)"]),
            }
        )
    return matrix


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.68,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "loxone_outputs": {"power_setpoint_name": "Ernie_EAuto_Ziel_kW"},
        "charging_schedule": {"enabled": True},
    }


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.97,
    }


def _urgent_dump_scenario(urgent_manifest: dict) -> tuple[list[dict], list[dict], dict, datetime, float]:
    reg = urgent_manifest["regression"]
    debug = json.loads(
        pdf.fixture_file(CASE_URGENT, "live_optimization_debug.json").read_text(encoding="utf-8")
    )
    rows = debug["simulation_rows"]
    matrix = _matrix_from_debug_rows(rows, reg["session_date"])
    deadline = _parse_ts(reg["deadline"])
    remaining = float(reg["remaining_kwh_at_correction"])
    contexts = {
        "eauto": {
            "active": True,
            "plugged_in": True,
            "deadline": deadline,
            "target_kwh": float(reg["corrected_target_kwh"]),
            "use_time_window": False,
        }
    }
    return rows, matrix, contexts, deadline, remaining


def _planned_kwh_breakdown(
    model,
    rows: list[dict],
    reg: dict,
) -> dict[str, float]:
    cheap_kwh = 0.0
    urgent_kwh = 0.0
    total_kwh = 0.0
    for index, row in enumerate(rows):
        hour = _hour_from_row(row)
        price = float(row["Strompreis (Cent/kWh)"])
        value = float(model.consumer_p["eauto"][index].varValue or 0.0)
        total_kwh += value
        if (
            reg["cheap_hour_from"] <= hour <= reg["cheap_hour_to"]
            and price <= float(reg["cheap_price_cent_max"])
        ):
            cheap_kwh += value
        if reg["urgent_hour_from"] <= hour <= reg["urgent_hour_to"]:
            urgent_kwh += value
    return {
        "total_kwh": round(total_kwh, 3),
        "cheap_kwh": round(cheap_kwh, 3),
        "urgent_kwh": round(urgent_kwh, 3),
    }


def _solve_urgent_dump_milp(
    urgent_manifest: dict,
    *,
    include_urgent_deadline_constraint: bool,
) -> dict:
    import pulp

    from optimizer.milp import (
        _add_consumer_delivery_constraints,
        _add_milp_objective,
        _build_milp_model,
        _collect_urgent_rule_observability,
    )

    reg = urgent_manifest["regression"]
    rows, matrix, contexts, _deadline, remaining = _urgent_dump_scenario(urgent_manifest)
    consumer = _eauto_consumer()
    model = _build_milp_model(
        matrix, len(matrix), _battery_params(), 10.0, [consumer], 0.0, {"eauto": 8.0},
        {
            "live_modus_a_min_remaining_kwh": 2.8,
            "tie_break_on_epsilon": 0.001,
            "tie_break_time_epsilon": 0.0001,
        },
    )
    _add_milp_objective(model, matrix, 3.7, {
        "live_modus_a_min_remaining_kwh": 2.8,
        "tie_break_on_epsilon": 0.001,
        "tie_break_time_epsilon": 0.0001,
    }, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(
        model,
        matrix,
        {"eauto": remaining},
        list(range(len(matrix))),
        contexts,
        False,
        include_urgent_deadline_constraint=include_urgent_deadline_constraint,
    )
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    breakdown = _planned_kwh_breakdown(model, rows, reg)
    observability = {}
    if include_urgent_deadline_constraint:
        observability = _collect_urgent_rule_observability(
            model,
            matrix,
            {"eauto": remaining},
            list(range(len(matrix))),
            contexts,
        )
    return {"breakdown": breakdown, "observability": observability}


@pytest.fixture(scope="module")
def eauto_manifest() -> dict:
    return pdf.load_manifest(CASE_EAUTO)


@pytest.fixture(scope="module")
def eauto_history() -> list[dict]:
    return pdf.load_jsonl(CASE_EAUTO)


@pytest.fixture(scope="module")
def urgent_manifest() -> dict:
    return pdf.load_manifest(CASE_URGENT)


@pytest.fixture(scope="module")
def false_complete_manifest() -> dict:
    return pdf.load_manifest(CASE_FALSE_COMPLETE)


@pytest.fixture(scope="module")
def false_complete_history() -> list[dict]:
    return pdf.load_jsonl(CASE_FALSE_COMPLETE)


def test_prod_dump_archives_are_discoverable():
    discovered = pdf.list_prod_dump_ids()
    for case_id in ALL_CASES:
        assert case_id in discovered


def test_prod_dump_documents_observed_failure(eauto_manifest, eauto_history):
    reg = eauto_manifest["regression"]
    start = _parse_ts(reg["session_start"])
    end = _parse_ts(reg["deadline"])
    live_kwh = _integrate_kw(eauto_history, start, end, "flex_live_kw")
    assert live_kwh < float(reg["target_kwh"])
    assert live_kwh <= float(reg["observed_live_kwh_max"]) + 0.5


def test_prod_dump_schedule_indices_cross_midnight(eauto_manifest):
    reg = eauto_manifest["regression"]
    start = _parse_ts(reg["session_start"])
    deadline = _parse_ts(reg["deadline"])
    matrix = [
        {
            "slot_datetime": start + timedelta(hours=i),
            "hour": (start + timedelta(hours=i)).hour,
            "date": (start + timedelta(hours=i)).date(),
        }
        for i in range(24)
    ]
    consumer = {
        "id": "eauto",
        "charging_schedule": {"enabled": True},
    }
    ctx = {
        "active": True,
        "deadline": deadline,
        "use_time_window": False,
    }
    indices = cc.schedule_indices_for_consumer(matrix, 24, [0, 1], consumer, ctx)
    assert len(indices) >= int(reg["min_schedule_indices_from_22h"])


def test_prod_dump_session_state_survives_midnight(eauto_manifest):
    reg = eauto_manifest["regression"]
    state_path = pdf.fixture_file(CASE_EAUTO, "flexible_consumers_state.json")
    prior = json.loads(state_path.read_text(encoding="utf-8"))
    consumer = {
        "id": "eauto",
        "charging_schedule": {"enabled": True},
    }
    contexts = {
        "eauto": {
            "active": True,
            "deadline": _parse_ts(reg["deadline"]),
            "target_kwh": float(reg["target_kwh"]),
        }
    }
    normalized = cs.normalize_consumer_state(
        prior,
        "2026-06-27",
        contexts,
        {"eauto": consumer},
        now=_parse_ts("2026-06-27T05:00:00"),
    )
    assert normalized["delivered"] == {}
    assert normalized["charging_sessions"]["eauto"]["delivered_kwh"] == 2.0


def test_prod_dump_urgent_window_covers_remaining_before_deadline(eauto_manifest):
    reg = eauto_manifest["regression"]
    start = _parse_ts("2026-06-27T05:00:00")
    deadline = _parse_ts(reg["deadline"])
    remaining = float(reg["target_kwh"])
    matrix = [
        {
            "slot_datetime": start + timedelta(hours=i),
            "hour": (start + timedelta(hours=i)).hour,
            "date": (start + timedelta(hours=i)).date(),
        }
        for i in range(6)
    ]
    eligible = list(range(len(matrix)))
    urgent = cc.urgent_charging_indices(matrix, eligible, deadline, remaining, 3.68)
    assert urgent
    urgent_energy_h = len(urgent)
    assert urgent_energy_h * 3.68 >= remaining * 0.95


def test_prod_dump_run_state_after_rest_soc_correction(urgent_manifest):
    reg = urgent_manifest["regression"]
    raw = json.loads(
        pdf.fixture_file(CASE_URGENT, "optimizer_run_state.json").read_text(encoding="utf-8")
    )
    ctx = raw["charging_contexts"]["eauto"]
    assert ctx["target_kwh"] == pytest.approx(float(reg["corrected_target_kwh"]), abs=0.001)
    assert ctx["deadline"] == reg["deadline"]
    assert raw["consumer_remaining_kwh"]["eauto"] == pytest.approx(
        float(reg["remaining_kwh_at_correction"]), abs=0.01
    )


def test_prod_dump_history_documents_plug_in_before_rest_soc(urgent_manifest):
    reg = urgent_manifest["regression"]
    history = pdf.load_jsonl(CASE_URGENT)
    plug_row = None
    soc_row = None
    for row in history:
        snap = row.get("event_trigger_snapshot") or {}
        ctx = (row.get("charging_contexts") or {}).get("eauto") or {}
        if row.get("run_trigger") != "event:eauto_plugged_in":
            continue
        if snap.get("eauto_rest_soc") != reg["plug_in_rest_soc_percent"]:
            continue
        if ctx.get("target_kwh") != reg["plug_in_target_kwh"]:
            continue
        plug_row = row
    for row in history:
        snap = row.get("event_trigger_snapshot") or {}
        ctx = (row.get("charging_contexts") or {}).get("eauto") or {}
        if row.get("run_trigger") != "event:eauto_rest_soc":
            continue
        if snap.get("eauto_rest_soc") != reg["corrected_rest_soc_percent"]:
            continue
        if ctx.get("target_kwh") != reg["corrected_target_kwh"]:
            continue
        soc_row = row
    assert plug_row is not None
    assert soc_row is not None


def test_prod_dump_archived_debug_shows_deferred_charging(urgent_manifest):
    reg = urgent_manifest["regression"]
    debug = json.loads(
        pdf.fixture_file(CASE_URGENT, "live_optimization_debug.json").read_text(encoding="utf-8")
    )
    cheap_max = 0.0
    urgent_values: list[float] = []
    for row in debug["simulation_rows"]:
        hour = _hour_from_row(row)
        eauto_kw = float(row.get("E-Auto (kW)", 0) or 0)
        price = float(row["Strompreis (Cent/kWh)"])
        if (
            reg["cheap_hour_from"] <= hour <= reg["cheap_hour_to"]
            and price <= float(reg["cheap_price_cent_max"])
        ):
            cheap_max = max(cheap_max, eauto_kw)
        if reg["urgent_hour_from"] <= hour <= reg["urgent_hour_to"]:
            urgent_values.append(eauto_kw)
    assert cheap_max <= float(reg["archived_debug_max_eauto_kw_cheap_hours"]) + 0.01
    assert urgent_values
    assert min(v for v in urgent_values if v > 0) >= float(
        reg["archived_debug_min_eauto_kw_urgent_hours"]
    ) - 0.01


@pytest.mark.xfail(
    reason="urgent-Nebenbedingung derzeit infeasible auf investigate/backtesting (Review offen)",
    strict=False,
)
def test_prod_dump_milp_prefers_cheap_hours_after_urgent_fix(urgent_manifest):
    with_urgent = _solve_urgent_dump_milp(
        urgent_manifest, include_urgent_deadline_constraint=True
    )
    assert with_urgent["breakdown"]["cheap_kwh"] >= 6.0


@pytest.mark.xfail(
    reason="urgent-Nebenbedingung derzeit infeasible auf investigate/backtesting (Review offen)",
    strict=False,
)
def test_prod_dump_urgent_rule_redundant_vs_deadline_only(urgent_manifest):
    """Prod-Dump 2026-06-28: Mit und ohne urgent-Nebenbedingung gleicher günstiger Plan."""
    reg = urgent_manifest["regression"]
    remaining = float(reg["remaining_kwh_at_correction"])

    with_urgent = _solve_urgent_dump_milp(
        urgent_manifest, include_urgent_deadline_constraint=True
    )
    without_urgent = _solve_urgent_dump_milp(
        urgent_manifest, include_urgent_deadline_constraint=False
    )

    assert with_urgent["observability"]["eauto"]["role"] == "redundant"
    assert with_urgent["breakdown"]["urgent_kwh"] == pytest.approx(0.0, abs=0.1)
    assert with_urgent["breakdown"]["total_kwh"] >= remaining * 0.95
    assert without_urgent["breakdown"]["total_kwh"] >= remaining * 0.95
    assert without_urgent["breakdown"]["urgent_kwh"] == pytest.approx(0.0, abs=0.1)
    assert without_urgent["breakdown"]["cheap_kwh"] == pytest.approx(
        with_urgent["breakdown"]["cheap_kwh"], abs=0.2
    )


def _history_row_at(history: list[dict], prefix: str) -> dict:
    for row in history:
        if str(row.get("written_at", "")).startswith(prefix):
            return row
    raise AssertionError(f"Kein History-Eintrag mit Präfix {prefix!r}")


def test_prod_dump_false_complete_documents_premature_zero(
    false_complete_manifest,
    false_complete_history,
):
    reg = false_complete_manifest["regression"]
    zero_row = _history_row_at(
        false_complete_history, reg["premature_remaining_zero_at"][:16]
    )
    rem = float((zero_row.get("consumer_remaining_kwh") or {}).get("eauto", -1))
    assert rem == pytest.approx(0.0, abs=0.001)
    live_kw = float((zero_row.get("flex_live_kw") or {}).get("eauto", 0.0))
    assert live_kw >= float(reg["min_live_kw_when_remaining_zero"])


def test_prod_dump_false_complete_morning_immediate_with_zero_remaining(
    false_complete_manifest,
    false_complete_history,
):
    reg = false_complete_manifest["regression"]
    morning = _history_row_at(
        false_complete_history, reg["morning_immediate_charge_at"][:16]
    )
    snap = morning.get("event_trigger_snapshot") or {}
    rem = float((morning.get("consumer_remaining_kwh") or {}).get("eauto", -1))
    assert snap.get("eauto_charge_immediate") is True
    assert rem == pytest.approx(0.0, abs=0.001)

    count = 0
    window_start = _parse_ts(reg["morning_immediate_charge_at"])
    window_end = _parse_ts(reg["deadline"]) + timedelta(hours=1)
    for row in false_complete_history:
        ts = _parse_ts(row["written_at"])
        if not (window_start <= ts <= window_end):
            continue
        snap = row.get("event_trigger_snapshot") or {}
        rem = float((row.get("consumer_remaining_kwh") or {}).get("eauto", -1))
        if rem == 0.0 and snap.get("eauto_charge_immediate") is True:
            count += 1
    assert count >= int(reg["morning_remaining_zero_with_immediate_count_min"])


def test_prod_dump_false_complete_plausibility_reopens_session(
    false_complete_manifest,
    false_complete_history,
):
    reg = false_complete_manifest["regression"]
    consumer = _eauto_consumer()
    ctx = {
        "active": True,
        "plugged_in": True,
        "deadline": _parse_ts(reg["deadline"]),
        "target_kwh": float(reg["corrected_target_kwh"]),
        "use_time_window": False,
    }
    morning = _history_row_at(
        false_complete_history, reg["morning_immediate_charge_at"][:16]
    )
    delivered = float(reg["corrected_target_kwh"])
    live_kw = float((morning.get("flex_live_kw") or {}).get("eauto", 0.0))
    effective, note = dt.assess_session_delivery(
        consumer,
        ctx,
        delivered,
        live_kw=live_kw,
        trigger_snapshot=morning.get("event_trigger_snapshot"),
    )
    assert note is not None
    assert note["role"] == "session_reopened"
    assert effective < delivered


def test_prod_dump_false_complete_live_booking_differs_from_planned(
    false_complete_manifest,
    false_complete_history,
):
    reg = false_complete_manifest["regression"]
    start = _parse_ts(reg["session_start"])
    end = _parse_ts(reg["premature_remaining_zero_at"])
    planned_kwh = _integrate_kw(false_complete_history, start, end, "consumer_powers_kw")
    live_kwh = _integrate_kw(false_complete_history, start, end, "flex_live_kw")
    assert planned_kwh <= float(reg["observed_planned_kwh_session_max"]) + 0.5
    assert live_kwh >= float(reg["observed_live_kwh_session_min"]) - 0.5
    assert live_kwh > planned_kwh
