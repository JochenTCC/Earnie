"""Sofort-Laden (E-Auto_SOFORT_LADEN): fixer Verbraucher, keine MILP-Planung."""
from __future__ import annotations

import copy
import logging
import math
from typing import Any

import config
from integrations import loxone_client
from optimizer.consumer_power import power_limits_kw
from optimizer.event_trigger import parse_binary_value

logger = logging.getLogger(__name__)

_SECONDS_PER_HOUR = 3600.0


def charge_immediate_io_name(consumer: dict) -> str:
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone") or {}
    return str(lox.get("charge_immediate_name", "")).strip()


def charge_immediate_remaining_io_name(consumer: dict) -> str:
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone") or {}
    return str(lox.get("charge_immediate_remaining_name", "")).strip()


def fetch_charge_immediate_switch(consumer: dict) -> bool | None:
    io_name = charge_immediate_io_name(consumer)
    if not io_name:
        return None
    return parse_binary_value(loxone_client.fetch_loxone_generic_value(io_name))


def charging_power_threshold_kw() -> float:
    return float(config.get_threshold_power())


def is_immediate_charging_active(
    consumer: dict,
    base_context: dict,
    *,
    switch_on: bool | None,
    live_kw: float | None,
) -> bool:
    if not switch_on or not charge_immediate_io_name(consumer):
        return False
    if base_context.get("plugged_in") is not True:
        return False

    threshold = charging_power_threshold_kw()
    if live_kw is not None and live_kw >= threshold:
        return True

    target_kwh = base_context.get("target_kwh")
    if target_kwh is not None and float(target_kwh) > threshold:
        return True
    return False


def immediate_horizon_slots(remaining_seconds: float | None, matrix_horizon: int) -> int:
    """Anzahl Matrix-Stunden mit Sofort-Laden aus Loxone-Restzeit (Sekunden)."""
    if remaining_seconds is None or remaining_seconds <= 0:
        return 0
    hours = float(remaining_seconds) / _SECONDS_PER_HOUR
    slots = int(math.ceil(hours - 1e-9))
    return min(max(0, slots), int(matrix_horizon))


def build_immediate_context(
    consumer: dict,
    base_context: dict,
    *,
    live_kw: float | None,
    max_kw: float,
    horizon_slots: int,
    remaining_seconds: float,
) -> dict:
    threshold = charging_power_threshold_kw()

    if live_kw is not None and live_kw >= threshold:
        current_kw = round(float(live_kw), 3)
    else:
        current_kw = round(max_kw, 3)

    remaining_hours = round(float(remaining_seconds) / _SECONDS_PER_HOUR, 2)

    return {
        **base_context,
        "active": False,
        "immediate_charge": True,
        "skip_loxone_output": True,
        "immediate_charge_kw": round(max_kw, 3),
        "immediate_charge_current_kw": current_kw,
        "immediate_horizon_hours": int(horizon_slots),
        "immediate_remaining_seconds": round(float(remaining_seconds), 1),
        "immediate_remaining_hours": remaining_hours,
        "source_label": "loxone (Sofort laden, Volllast)",
    }


def enrich_context_with_immediate_charge(
    consumer: dict,
    context: dict,
    *,
    live_kw: float | None,
    horizon: int,
) -> dict:
    if not charge_immediate_io_name(consumer):
        return context
    if consumer.get("daily_target_source") != "loxone":
        return context

    switch_on = fetch_charge_immediate_switch(consumer)
    if live_kw is None:
        live_kw = loxone_client.resolve_consumer_live_power_kw(consumer)

    if not is_immediate_charging_active(
        consumer, context, switch_on=switch_on, live_kw=live_kw
    ):
        return context

    remaining_seconds = loxone_client.fetch_charge_immediate_remaining_seconds(consumer)
    horizon_slots = immediate_horizon_slots(remaining_seconds, horizon)
    if horizon_slots <= 0:
        if remaining_seconds is None:
            logger.warning(
                "%s: Sofort-Laden aktiv, aber keine gültige Restladezeit von Loxone "
                "(%s) – keine Planung als fixer Verbraucher.",
                consumer["name"],
                charge_immediate_remaining_io_name(consumer) or "?",
            )
        else:
            logger.info(
                "%s: Sofort-Laden aktiv, Restladezeit abgelaufen – keine Planung.",
                consumer["name"],
            )
        return context

    _, max_kw = power_limits_kw(consumer)
    result = build_immediate_context(
        consumer,
        context,
        live_kw=live_kw,
        max_kw=max_kw,
        horizon_slots=horizon_slots,
        remaining_seconds=float(remaining_seconds),
    )
    logger.info(
        "%s: Sofort-Laden aktiv (%s=1) – %.2f kW fix für noch %.2f h "
        "(%s s, %s Slots), keine flexible MILP-Planung.",
        consumer["name"],
        charge_immediate_io_name(consumer),
        result["immediate_charge_kw"],
        result["immediate_remaining_hours"],
        int(remaining_seconds),
        horizon_slots,
    )
    return result


def _fixed_kw_for_slot(
    t: int,
    *,
    max_kw: float,
    current_kw: float,
    flex_eauto: float,
) -> float:
    if t == 0:
        if flex_eauto > 0:
            return max(current_kw, flex_eauto)
        return current_kw
    return max_kw


def apply_immediate_charge_to_matrix(
    matrix: list[dict[str, Any]],
    contexts: dict[str, dict],
    consumers: list | None = None,
) -> list:
    """Verlagert E-Auto-Last von flex in Grundlast für die Planungsmatrix."""
    if not matrix:
        return matrix

    source = consumers if consumers is not None else config.get_flexible_consumers(
        optimizer_only=True
    )
    updated = copy.deepcopy(matrix)
    horizon = len(updated)

    for consumer in source:
        cid = consumer["id"]
        ctx = contexts.get(cid) or {}
        if not ctx.get("immediate_charge"):
            continue

        max_kw = float(ctx["immediate_charge_kw"])
        current_kw = float(ctx.get("immediate_charge_current_kw", max_kw))
        hours = int(ctx.get("immediate_horizon_hours", 1))

        for t in range(min(hours, horizon)):
            row = updated[t]
            flex = dict(row.get("expected_flex_kw") or {})
            flex_eauto = float(flex.pop(cid, 0.0) or 0.0)
            add_kw = _fixed_kw_for_slot(
                t, max_kw=max_kw, current_kw=current_kw, flex_eauto=flex_eauto
            )
            row["expected_p_act"] = round(float(row.get("expected_p_act", 0.0)) + add_kw, 3)
            row["expected_flex_kw"] = flex
            total_flex = sum(float(v or 0.0) for v in flex.values())
            row["expected_p_total"] = round(float(row.get("expected_p_act", 0.0)) + total_flex, 3)

    return updated


def live_flex_kw_from_matrix(matrix: list) -> dict[str, float] | None:
    if not matrix or matrix[0].get("consumption_mode") != "live_snapshot":
        return None
    flex = matrix[0].get("expected_flex_kw")
    if not isinstance(flex, dict) or not flex:
        return None
    return dict(flex)


def prepare_optimization_matrix(
    matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
    *,
    consumers: list | None = None,
) -> tuple[list, dict[str, dict], dict[str, float]]:
    """Ladekontexte auflösen und Sofort-Laden in die Optimierungsmatrix einrechnen."""
    from data import consumer_targets
    from .charging_context import resolve_charging_contexts

    targets = consumer_daily_targets_kwh
    if targets is None:
        targets = consumer_targets.resolve_consumer_daily_targets(matrix=matrix)

    live_flex_kw = live_flex_kw_from_matrix(matrix)
    live_consumers = consumers
    if live_consumers is None and live_flex_kw is not None:
        live_consumers = loxone_client.consumers_with_live_nominal_power()

    contexts = resolve_charging_contexts(
        matrix,
        targets,
        live_flex_kw=live_flex_kw,
        consumers=live_consumers,
    )
    prepared = apply_immediate_charge_to_matrix(matrix, contexts, live_consumers)
    return prepared, contexts, targets


def immediate_charge_kw_for_hour(hour_index: int, ctx: dict) -> float:
    """Fixe Sofort-Ladeleistung für eine Chart-/Matrix-Stunde."""
    if not ctx.get("immediate_charge"):
        return 0.0
    hours = int(ctx.get("immediate_horizon_hours", 0))
    if hour_index < 0 or hour_index >= hours:
        return 0.0
    if hour_index == 0:
        return float(ctx.get("immediate_charge_current_kw", ctx.get("immediate_charge_kw", 0.0)))
    return float(ctx.get("immediate_charge_kw", 0.0))


def apply_immediate_charge_chart_display(
    chart_row: dict,
    hour_index: int,
    charging_contexts: dict[str, dict] | None,
    *,
    flex_live_kw: dict[str, float] | None = None,
) -> None:
    """
    Zeigt Sofort-Laden als Flex-Balken (Karo-Schraffur), Grundlast ohne E-Auto-Anteil.
    Physik (Netzbezug) bleibt unverändert.
    """
    from optimizer.targets import (
        consumer_column_name,
        consumer_immediate_charge_column_name,
    )

    if not charging_contexts:
        return

    moved_kw = 0.0
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        imm_col = consumer_immediate_charge_column_name(consumer)
        ctx = charging_contexts.get(cid) or {}
        kw = immediate_charge_kw_for_hour(hour_index, ctx)
        if hour_index == 0 and flex_live_kw is not None and ctx.get("immediate_charge"):
            live = flex_live_kw.get(cid)
            if live is not None and float(live) >= charging_power_threshold_kw():
                kw = max(kw, float(live))
        power_col = consumer_column_name(consumer)
        if kw <= 1e-6:
            chart_row[imm_col] = 0
            continue
        chart_row[power_col] = round(kw, 2)
        chart_row[imm_col] = 1
        moved_kw += kw

    if moved_kw <= 1e-6:
        return

    chart_row["Verbrauch-Prognose (kW)"] = round(
        float(chart_row["Verbrauch-Prognose (kW)"]) - moved_kw,
        2,
    )
    pv = float(chart_row["PV-Prognose (kW)"])
    batt = float(chart_row["Geplante Batterie-Aktion (kW)"])
    flex_sum = sum(
        float(chart_row.get(consumer_column_name(c), 0.0) or 0.0)
        for c in config.get_flexible_consumers(optimizer_only=True)
    )
    con = float(chart_row["Verbrauch-Prognose (kW)"])
    chart_row["Netzbezug (kW)"] = round(con + flex_sum - pv + batt, 2)


def apply_immediate_charge_to_chart_rows(
    chart_rows: list[dict],
    charging_contexts: dict[str, dict] | None,
    *,
    flex_live_kw: dict[str, float] | None = None,
) -> None:
    """Wendet Sofort-Laden-Darstellung auf alle Chart-Zeilen an (in-place)."""
    if not chart_rows or not charging_contexts:
        return
    for hour_index, chart_row in enumerate(chart_rows):
        live = flex_live_kw if hour_index == 0 else None
        apply_immediate_charge_chart_display(
            chart_row,
            hour_index,
            charging_contexts,
            flex_live_kw=live,
        )


def immediate_charging_labels(contexts: dict[str, dict]) -> list[str]:
    """Kurztexte für UI/Logs bei aktivem Sofort-Laden."""
    labels: list[str] = []
    for cid, ctx in contexts.items():
        if not ctx.get("immediate_charge"):
            continue
        remaining_h = ctx.get("immediate_remaining_hours")
        if remaining_h is not None:
            labels.append(
                f"{cid}: {ctx.get('immediate_charge_kw')} kW fix "
                f"(noch {remaining_h} h, Loxone)"
            )
        else:
            labels.append(
                f"{cid}: {ctx.get('immediate_charge_kw')} kW fix "
                f"(bis {ctx.get('immediate_horizon_hours')} h)"
            )
    return labels


def immediate_charging_labels_from_main_state(main_state: dict | None) -> list[str]:
    """Fallback-Labels aus main.py run_state (Event-Trigger + Live-Leistung)."""
    if not main_state:
        return []
    snap = main_state.get("event_trigger_snapshot") or {}
    if not snap.get("eauto_charge_immediate"):
        return []
    if snap.get("eauto_plugged_in") is False:
        return []
    ctx = (main_state.get("charging_contexts") or {}).get("eauto") or {}
    if ctx.get("immediate_charge"):
        return immediate_charging_labels({"eauto": ctx})
    flex_kw = (main_state.get("flex_live_kw") or {}).get("eauto")
    threshold = charging_power_threshold_kw()
    target_kwh = ctx.get("target_kwh")
    if flex_kw is not None and float(flex_kw) < threshold:
        if target_kwh is None or float(target_kwh) <= threshold:
            return []
    kw = round(float(flex_kw), 3) if flex_kw is not None else None
    if kw is None:
        kw = ctx.get("immediate_charge_kw")
    if kw is None:
        return ["eauto: Sofort-Laden (Volllast)"]
    return [f"eauto: {kw} kW live (Sofort-Laden)"]


def merge_immediate_charging_labels(
    contexts: dict[str, dict],
    main_state: dict | None,
) -> list[str]:
    labels = immediate_charging_labels(contexts)
    if labels:
        return labels
    return immediate_charging_labels_from_main_state(main_state)
