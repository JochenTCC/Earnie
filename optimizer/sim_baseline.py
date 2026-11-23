"""Baseline and matched-baseline horizon simulation.

Import facade: the L1 / L2 reference flex lives in ``optimizer.sim_reference_flex`` and is
re-exported here; patch a moved name there (see ``.cursor/rules/import-facades.mdc``).
"""
from __future__ import annotations

import logging

import config
from settings.flexible_consumers import flex_kw_lookup
from optimizer import battery as bat
from optimizer.milp_horizon import (
    coerce_battery_params_list,
    plant_battery_params,
)
from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.sim_chart_rows import (
    COL_VERBRAUCH_PROGNOSE,
    _chart_price_fields,
    _chart_row_slot_field,
    _finalize_chart_rows_for_display,
    _format_chart_uhrzeit,
)
from optimizer.sim_reference_flex import (  # noqa: F401  (re-exported: L1/L2 reference flex)
    DEFAULT_RULE_PARAMS,
    SURPLUS_BATTERY_FIRST,
    SURPLUS_CONSUMER_FIRST,
    RuleBasedFlex,
    ShapedFlex,
    SurplusRod,
    _ENERGY_EPSILON_KWH,
    _POWER_EPSILON_KW,
    _PRICE_EPSILON_CENT,
    _RuleConsumer,
    _available_surplus_kw,
    _contiguous_runs,
    _export_left_kw,
    _is_ev_consumer,
    _is_nonexistent_local_slot,
    _last_published_stop,
    _lock_horizon_truncated,
    _move_to_cheapest_block,
    _price_locked,
    _rule_consumer,
    _spread_with_power_cap,
    _surplus_threshold_kw,
    _validated_rule_params,
    available_slot_prices,
    build_rule_based_flex_kw_per_hour,
    build_shaped_flex_kw_per_slot,
)
from optimizer.targets import consumer_column_name

logger = logging.getLogger(__name__)


def _baseline_battery_params(
    battery_params: dict | list[dict] | None,
) -> dict:
    """Baseline battery: the plant battery of the optimized run.

    One house battery is taken as is. With several the baseline runs the same plant as the
    optimized open-loop run (``plant_battery_params`` over the house-balance batteries), as
    does the savings ledger's shadow plant (``docs/dev/savings-ledger.md`` § 3). ``None``
    reads the live config's batteries.
    """
    if battery_params is None:
        listed = coerce_battery_params_list(config.get_battery_params_list())
        if len(listed) < 2:
            return config.get_battery_params()
        batteries = listed
    else:
        batteries = coerce_battery_params_list(battery_params)
        if not batteries:
            return config.get_battery_params()
        if len(batteries) == 1:
            return batteries[0]
    from optimizer.sim_horizon_chart_soc import house_balance_batteries

    return plant_battery_params(house_balance_batteries(batteries))


def _matched_baseline_profile_kw(row: dict, consumer: dict) -> float:
    """Flex kW used as matched-baseline *shape*.

    ``live_snapshot`` is the current meter reading, not a historical day profile.
    Scaling a full horizon target onto that single QH sample yields
    ``target / dt_h`` kW (factor 4 at ``DEFAULT_DT_H=0.25``) and inflated BL Ziel €.
    """
    if row.get("consumption_mode") == "live_snapshot":
        return 0.0
    return flex_kw_lookup(row.get("expected_flex_kw") or {}, consumer)


def build_matched_flex_kw_per_hour(
    optimization_matrix: list,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    *,
    consumers: list[dict] | None = None,
) -> list[dict[str, float]]:
    """
    Skaliert das historische Flex-Profil auf die aktuellen Horizont-Ziele (kWh).
    ``consumers``: flex consumers of the window (default: the live scenario's).
    Zeitliche Form bleibt erhalten (auch unter Nennleistung); außerhalb des
    Ladezeitfensters null – wie im MILP. Live-Snapshot-Slots zählen nicht als Profil.
    No slot exceeds the nominal power: the excess moves to other eligible slots
    (``_cap_matched_flex_at_nominal``).
    """
    # Resolve via simulation facade so tests can monkeypatch
    # ``optimizer.simulation.config`` / ``consumer_charging_eligible_indices``.
    from optimizer import simulation as sim

    consumers_cfg = (
        consumers
        if consumers is not None
        else sim.config.get_flexible_consumers(optimizer_only=True)
    )
    rows = optimization_matrix
    hour_count = len(rows)
    contexts = charging_contexts or {}
    schedule_indices = list(range(hour_count))

    eligible_by_consumer: dict[str, set[int]] = {}
    for consumer in consumers_cfg:
        cid = consumer["id"]
        eligible = sim.consumer_charging_eligible_indices(
            rows,
            consumer,
            schedule_indices,
            contexts.get(cid),
        )
        eligible_by_consumer[cid] = set(eligible)

    dt_h = float(DEFAULT_DT_H)
    per_hour: list[dict[str, float]] = [{} for _ in range(hour_count)]
    for consumer in consumers_cfg:
        cid = consumer["id"]
        target = float(consumer_targets_kwh.get(cid, 0.0) or 0.0)
        eligible = sorted(eligible_by_consumer[cid])
        profile_kw = {t: _matched_baseline_profile_kw(rows[t], consumer) for t in eligible}
        profile_sum = sum(profile_kw.values())
        if profile_sum > 1e-6:
            # target is kWh; profile_sum is Σ kW → scale so Σ(kW)*dt_h = target
            scale = target / (profile_sum * dt_h)
            desired = {t: kw * scale for t, kw in profile_kw.items()}
        elif target > 0 and eligible:
            desired = {t: target / (len(eligible) * dt_h) for t in eligible}
        else:
            desired = {}
        delivered = _cap_matched_flex_at_nominal(consumer, desired, eligible)
        for t in range(hour_count):
            per_hour[t][cid] = delivered.get(t, 0.0)
    return per_hour


def _cap_matched_flex_at_nominal(
    consumer: dict,
    desired_kw: dict[int, float],
    eligible: list[int],
) -> dict[int, float]:
    """No slot above the consumer's nominal power; the excess moves to other eligible slots.

    A profile with its energy in a few slots, scaled to a larger target, would otherwise ask
    for power the consumer cannot draw. Energy the eligible slots cannot take at nominal power
    is left out and logged: the baseline then holds less than the target.
    """
    if not desired_kw:
        return {}
    max_kw = float(consumer["nominal_power_kw"])
    delivered, undelivered_kw = _spread_with_power_cap(desired_kw, eligible, max_kw)
    missing_kwh = undelivered_kw * float(DEFAULT_DT_H)
    if missing_kwh > _ENERGY_EPSILON_KWH:
        logger.warning(
            "BL Ziel: Verbraucher '%s' erreicht sein Ziel nicht, es fehlen %.3f kWh "
            "(%d zulässige Slots, max. %g kW).",
            consumer["id"],
            missing_kwh,
            len(eligible),
            max_kw,
        )
    return delivered


def _simulate_single_hour_baseline(
    row: dict,
    sim_soc: float,
    battery_params: dict,
    flex_kw_override: dict[str, float] | None = None,
    steuerbefehl: str = "Baseline",
    consumption_kw_override: float | None = None,
    *,
    consumers: list[dict] | None = None,
) -> tuple[float, dict]:
    """Simuliert eine einzelne Stunde im Baseline-Pfad.

    ``consumers`` names the flex columns of the chart row (default: the live scenario's).
    ``consumption_kw_override``: consumption without flex, battery standby included (as in
    the chart column), so no standby is added to it.
    """
    pv = row["expected_p_pv"]
    flex_kw = flex_kw_override if flex_kw_override is not None else (row.get("expected_flex_kw") or {})
    has_flex_profile = any(float(v or 0.0) > 0.0 for v in flex_kw.values())
    simulation_mode = row.get("consumption_mode") in ("logged_day", "profile_spec")
    if flex_kw_override is None and simulation_mode and not has_flex_profile:
        con = float(row.get("expected_p_total", row["expected_p_act"]) or 0.0)
        con = con + bat.standby_power_kw(battery_params)
        total_flex_power = 0.0
        flex_kw = {}
    elif consumption_kw_override is not None:
        con = float(consumption_kw_override)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    else:
        con = bat.effective_p_act(row, battery_params)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    net_pv_surplus = pv - con - total_flex_power
    old_soc = sim_soc
    sim_soc, batt_action = bat.vendor_mode_step(
        old_soc, net_pv_surplus, battery_params, dt_h=DEFAULT_DT_H
    )
    p_grid = con + total_flex_power - pv + round(batt_action, 2)
    chart_row = {
        "Uhrzeit": _format_chart_uhrzeit(row),
        **_chart_row_slot_field(row),
        **_chart_price_fields(row),
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Netzbezug (kW)": round(p_grid, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": steuerbefehl,
    }
    column_consumers = (
        consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)
    )
    for consumer in column_consumers:
        if flex_kw:
            chart_row[consumer_column_name(consumer)] = round(
                float(flex_kw.get(consumer["id"], 0.0) or 0.0), 2
            )
    return sim_soc, chart_row


def simulate_baseline_horizon(
    optimization_matrix: list,
    initial_soc: float,
    charging_contexts: dict[str, dict] | None = None,
    *,
    battery_params: dict | list[dict] | None = None,
    consumers: list[dict] | None = None,
) -> list:
    """Simuliert den 24h-Verlauf ohne Optimierung: Batterie folgt nur dem aktuellen PV-Überschuss.

    ``consumers``: flex consumers of the window (default: the live scenario's).
    """
    chart_rows = []
    sim_soc = initial_soc
    battery_params = _baseline_battery_params(battery_params)
    for row in optimization_matrix:
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row, sim_soc, battery_params, consumers=consumers
        )
        chart_rows.append(chart_row)
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    return chart_rows


def _flex_kw_from_chart_row(
    chart_row: dict, consumers: list[dict] | None = None
) -> dict[str, float]:
    """Flex-Leistungen je Verbraucher aus einer Simulationszeile."""
    source = (
        consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)
    )
    return {
        consumer["id"]: float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        for consumer in source
    }


def _consumption_kw_of_optimized_row(
    optimized_row: dict, row: dict, battery_params: dict
) -> float:
    """Consumption without flex of the optimized run, battery standby included.

    The chart column already holds the standby; a row without the column gets the matrix
    load plus standby.
    """
    if COL_VERBRAUCH_PROGNOSE in optimized_row:
        return float(optimized_row[COL_VERBRAUCH_PROGNOSE] or 0.0)
    return bat.effective_p_act(row, battery_params)


def simulate_baseline_with_optimized_flex(
    optimization_matrix: list,
    optimized_rows: list,
    initial_soc: float,
    *,
    battery_params: dict | list[dict] | None = None,
    consumers: list[dict] | None = None,
) -> list:
    """
    Baseline-Batterie (nur PV-Überschuss), aber dieselbe stündliche Flex-Last wie optimiert.
    Für den stündlichen Kostenvergleich: gleiche Last, Unterschied nur Batterie/Netz.
    """
    battery_params = _baseline_battery_params(battery_params)
    sim_soc = initial_soc
    chart_rows: list[dict] = []
    for row, optimized_row in zip(optimization_matrix, optimized_rows):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=_flex_kw_from_chart_row(optimized_row, consumers),
            steuerbefehl="Baseline (Ziel)",
            consumption_kw_override=_consumption_kw_of_optimized_row(
                optimized_row, row, battery_params
            ),
            consumers=consumers,
        )
        chart_rows.append(chart_row)
    return chart_rows


def simulate_matched_baseline_horizon(
    optimization_matrix: list,
    initial_soc: float,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    *,
    battery_params: dict | list[dict] | None = None,
    consumers: list[dict] | None = None,
) -> list:
    """
    Baseline mit gleicher Flex-Energie wie die Optimierung,
    aber ohne Preis-Lastverschiebung – Batterie nur PV-Überschuss.
    """
    matched_flex = build_matched_flex_kw_per_hour(
        optimization_matrix,
        consumer_targets_kwh,
        charging_contexts,
        consumers=consumers,
    )
    chart_rows = []
    sim_soc = initial_soc
    battery_params = _baseline_battery_params(battery_params)
    for row, flex_kw in zip(optimization_matrix, matched_flex):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=flex_kw,
            steuerbefehl="Baseline (Ziel)",
            consumers=consumers,
        )
        chart_rows.append(chart_row)
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    return chart_rows
