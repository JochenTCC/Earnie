"""Tier-1 prod-dump invariants for L1-invariants regression cases.

Shares the documented failure checks with ``tests/test_prod_dump_regression.py``
(fast per-commit guards stay there; this module is the suite entry point).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from tests.fixtures import prod_dump_fixtures as pdf

CASE_EAUTO = "eauto_deadline_missed_2026-06-27"
CASE_URGENT = "eauto_urgent_deferred_cheap_hours_2026-06-28"
CASE_URGENT_JULY = "eauto_urgent_deferred_cheap_hours_2026-07-09"
CASE_FALSE_COMPLETE = "eauto_false_complete_2026-06-29"


def run_prod_dump_invariants(prod_dump_id: str) -> list[str]:
    """Return human-readable failure messages (empty = pass)."""
    checkers = {
        CASE_EAUTO: _check_eauto_deadline,
        CASE_URGENT: _check_urgent_june,
        CASE_URGENT_JULY: _check_urgent_july,
        CASE_FALSE_COMPLETE: _check_false_complete,
    }
    checker = checkers.get(prod_dump_id)
    if checker is None:
        return [f"unknown prod_dump_id {prod_dump_id!r}"]
    try:
        return checker()
    except Exception as exc:  # noqa: BLE001 — surface as invariant failure
        return [f"{prod_dump_id}: raised {type(exc).__name__}: {exc}"]


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
    raw_slot = row.get("slot_datetime")
    if raw_slot:
        return datetime.fromisoformat(str(raw_slot)).hour
    uhrzeit = str(row["Uhrzeit"])
    if " " in uhrzeit:
        return int(uhrzeit.split()[-1].split(":")[0])
    return int(uhrzeit.split(":")[0])


def _check_eauto_deadline() -> list[str]:
    failures: list[str] = []
    manifest = pdf.load_manifest(CASE_EAUTO)
    history = pdf.load_jsonl(CASE_EAUTO)
    reg = manifest["regression"]
    start = _parse_ts(reg["session_start"])
    end = _parse_ts(reg["deadline"])
    live_kwh = _integrate_kw(history, start, end, "flex_live_kw")
    if not (live_kwh < float(reg["target_kwh"])):
        failures.append(
            f"live_kwh {live_kwh} not < target {reg['target_kwh']} (documented miss)"
        )
    if live_kwh > float(reg["observed_live_kwh_max"]) + 0.5:
        failures.append(
            f"live_kwh {live_kwh} exceeds observed_live_kwh_max "
            f"{reg['observed_live_kwh_max']}+0.5"
        )
    return failures


def _check_urgent_june() -> list[str]:
    return _check_urgent_archived_debug(CASE_URGENT)


def _check_urgent_july() -> list[str]:
    return _check_urgent_archived_debug(CASE_URGENT_JULY)


def _check_urgent_archived_debug(case_id: str) -> list[str]:
    failures: list[str] = []
    manifest = pdf.load_manifest(case_id)
    reg = manifest["regression"]
    debug = json.loads(
        pdf.fixture_file(case_id, "live_optimization_debug.json").read_text(
            encoding="utf-8"
        )
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
    if cheap_max > float(reg["archived_debug_max_eauto_kw_cheap_hours"]) + 0.01:
        failures.append(
            f"{case_id}: cheap-hour eauto_kw {cheap_max} exceeds archive max"
        )
    if not urgent_values:
        failures.append(f"{case_id}: no urgent-hour rows in archived debug")
    else:
        positive = [v for v in urgent_values if v > 0]
        if positive and min(positive) < float(
            reg["archived_debug_min_eauto_kw_urgent_hours"]
        ) - 0.01:
            failures.append(
                f"{case_id}: urgent-hour min eauto_kw below archive minimum"
            )
    # Run-state correction present
    raw = json.loads(
        pdf.fixture_file(case_id, "optimizer_run_state.json").read_text(encoding="utf-8")
    )
    ctx = raw["charging_contexts"]["eauto"]
    if abs(float(ctx["target_kwh"]) - float(reg["corrected_target_kwh"])) > 0.001:
        failures.append(f"{case_id}: corrected target_kwh mismatch in run state")
    return failures


def _check_false_complete() -> list[str]:
    failures: list[str] = []
    manifest = pdf.load_manifest(CASE_FALSE_COMPLETE)
    history = pdf.load_jsonl(CASE_FALSE_COMPLETE)
    reg = manifest["regression"]

    def row_at(prefix: str) -> dict[str, Any]:
        for row in history:
            if str(row.get("written_at", "")).startswith(prefix):
                return row
        raise AssertionError(f"no history row with prefix {prefix!r}")

    zero_row = row_at(reg["premature_remaining_zero_at"][:16])
    rem = float((zero_row.get("consumer_remaining_kwh") or {}).get("eauto", -1))
    if abs(rem) > 0.001:
        failures.append("premature remaining was not zero")
    live_kw = float((zero_row.get("flex_live_kw") or {}).get("eauto", 0.0))
    if live_kw < float(reg["min_live_kw_when_remaining_zero"]):
        failures.append("live_kw at premature zero below minimum")

    morning = row_at(reg["morning_immediate_charge_at"][:16])
    snap = morning.get("event_trigger_snapshot") or {}
    rem_m = float((morning.get("consumer_remaining_kwh") or {}).get("eauto", -1))
    if snap.get("eauto_charge_immediate") is not True:
        failures.append("morning immediate charge flag missing")
    if abs(rem_m) > 0.001:
        failures.append("morning remaining was not zero")

    start = _parse_ts(reg["session_start"])
    end = _parse_ts(reg["premature_remaining_zero_at"])
    planned = _integrate_kw(history, start, end, "consumer_powers_kw")
    live = _integrate_kw(history, start, end, "flex_live_kw")
    if planned > float(reg["observed_planned_kwh_session_max"]) + 0.5:
        failures.append("planned kWh above documented session max")
    if live < float(reg["observed_live_kwh_session_min"]) - 0.5:
        failures.append("live kWh below documented session min")
    if not (live > planned):
        failures.append("live kWh not greater than planned (false-complete symptom)")
    return failures
