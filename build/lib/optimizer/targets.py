"""Zielenergie-Auflösung und UI-Detail-Builder für flexible Verbraucher."""
from __future__ import annotations

from datetime import datetime, time

import config
from .charging_context import (
    apply_horizon_charging_limits,
    resolve_charging_contexts,
)


def consumer_column_name(consumer: dict) -> str:
    return f"{consumer['name']} (kW)"


def consumer_pv_follow_column_name(consumer: dict) -> str:
    return f"{consumer['name']} pv_follow"


def consumer_immediate_charge_column_name(consumer: dict) -> str:
    return f"{consumer['name']} sofort_laden"


def min_delivery_kwh(consumer: dict) -> float:
    """Mindest-Energie (kWh) für eine einzelne Einschaltperiode (min_on_quarterhours)."""
    min_hours = max(1, (int(consumer["min_on_quarterhours"]) + 3) // 4)
    return consumer["nominal_power_kw"] * min_hours


def feasible_target_kwh(consumer: dict, target: float, day_hours: int) -> float:
    """Rundet das Ziel auf die kleinste mit min_on erreichbare Energiemenge (volle Stunden à Nennleistung)."""
    if target <= 0:
        return 0.0
    power = consumer["nominal_power_kw"]
    min_hours = max(1, (int(consumer["min_on_quarterhours"]) + 3) // 4)
    for hours in range(min_hours, day_hours + 1):
        if hours * power >= target - 1e-6:
            return hours * power
    return day_hours * power


def max_delivery_cap_kwh(consumer: dict, target: float, day_hours: int) -> float:
    """Obergrenze für Flex-Energie: Ziel plus höchstens eine Mindestperiode (min_on-Granularität)."""
    return feasible_target_kwh(consumer, target, day_hours)


def resolve_daily_target_kwh(
    consumer: dict,
    consumer_daily_targets_kwh: dict | None,
    row_date=None,
    logged_targets_only: bool = False,
    ref_datetime: datetime | None = None,
    horizon_flex_kwh: float | None = None,
) -> float:
    """Tagesziel aus Overrides oder – je nach Modus – Logs bzw. daily_target_source."""
    cid = consumer["id"]
    if consumer_daily_targets_kwh is not None and logged_targets_only:
        if row_date is not None and row_date in consumer_daily_targets_kwh:
            day_targets = consumer_daily_targets_kwh[row_date]
            if isinstance(day_targets, dict) and cid in day_targets:
                return float(day_targets[cid])
        if cid in consumer_daily_targets_kwh:
            return float(consumer_daily_targets_kwh[cid])
    if logged_targets_only:
        from data import consumer_targets
        if row_date is None:
            return 0.0
        logged = consumer_targets.resolve_historical_consumer_daily_targets(row_date)
        return float(logged.get(cid, 0.0))
    if (
        consumer.get("daily_target_source", "config") == "historical"
        and horizon_flex_kwh is not None
    ):
        return float(horizon_flex_kwh)
    from data import consumer_targets
    day = row_date or datetime.now().date()
    when = ref_datetime or datetime.combine(day, time(12, 0))
    if (
        consumer.get("daily_target_source", "config") == "config"
        and consumer.get("charging_schedule", {}).get("enabled")
    ):
        from integrations import loxone_client

        capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
        computed = config.Config.target_kwh_from_day_schedule(
            consumer, when, capacity_kwh=capacity_kwh
        )
        if computed is not None:
            return float(computed)
    resolved = consumer_targets.resolve_consumer_daily_targets(target_date=day)
    return float(resolved.get(cid, consumer.get("daily_target_kwh", 0.0)))


def resolve_horizon_target_kwh(
    consumer: dict,
    consumer_daily_targets_kwh: dict | None,
    row_date=None,
    logged_targets_only: bool = False,
    ref_datetime: datetime | None = None,
    horizon_flex_kwh: float | None = None,
) -> float:
    return resolve_daily_target_kwh(
        consumer,
        consumer_daily_targets_kwh,
        row_date,
        logged_targets_only,
        ref_datetime=ref_datetime,
        horizon_flex_kwh=horizon_flex_kwh,
    )


def is_flat_target_override(consumer_daily_targets_kwh: dict | None) -> bool:
    """True, wenn das Dict flache Verbraucher-IDs enthält (nicht {date: {id: kwh}})."""
    if not consumer_daily_targets_kwh:
        return False
    return not any(isinstance(v, dict) for v in consumer_daily_targets_kwh.values())


def resolve_horizon_consumer_targets_kwh(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
    *,
    flexible_consumers: list | None = None,
) -> dict[str, float]:
    """
    Flex-Zielenergie je Verbraucher für den gesamten Planungshorizont (einmalig).
    Kein erneutes Zählen bei Kalendertagwechsel im rollierenden Horizont.
    """
    consumers_cfg = flexible_consumers or config.get_flexible_consumers(
        optimizer_only=True
    )
    if not optimization_matrix:
        return {c["id"]: 0.0 for c in consumers_cfg}
    logged_targets_only = optimization_matrix[0].get("consumption_mode") in (
        "logged_day",
        "profile_spec",
    )
    ref_date = optimization_matrix[0].get("date")
    ref_dt = optimization_matrix[0].get("slot_datetime")
    if not isinstance(ref_dt, datetime):
        ref_dt = (
            datetime.combine(ref_date, time(12, 0))
            if ref_date is not None
            else datetime.now()
        )
    if is_flat_target_override(consumer_daily_targets_kwh) and logged_targets_only:
        return {
            c["id"]: round(float(consumer_daily_targets_kwh.get(c["id"], 0.0)), 3)
            for c in consumers_cfg
        }
    horizon_flex_targets = None
    if not logged_targets_only:
        from data import consumer_targets
        horizon_flex_targets = consumer_targets.resolve_horizon_flex_targets_kwh(
            optimization_matrix
        )
    return {
        c["id"]: round(
            resolve_horizon_target_kwh(
                c,
                consumer_daily_targets_kwh,
                ref_date,
                logged_targets_only,
                ref_datetime=ref_dt,
                horizon_flex_kwh=(
                    horizon_flex_targets.get(c["id"])
                    if horizon_flex_targets is not None
                    else None
                ),
            ),
            3,
        )
        for c in consumers_cfg
    }


def resolve_applied_daily_targets(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> dict[str, float]:
    """Ermittelt die Tagesziele, die die Simulation tatsächlich verwendet."""
    return resolve_horizon_consumer_targets_kwh(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )


def build_applied_targets_detail(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> list[dict]:
    """Bereitet die genutzten Tagesziele mit Verbrauchername und Quelle für die UI auf."""
    consumption_mode = (
        optimization_matrix[0].get("consumption_mode") if optimization_matrix else None
    )
    logged_day = consumption_mode == "logged_day"
    targets = resolve_applied_daily_targets(optimization_matrix, consumer_daily_targets_kwh)
    charging_contexts = resolve_charging_contexts(optimization_matrix, consumer_daily_targets_kwh)
    targets = apply_horizon_charging_limits(targets, charging_contexts)
    details = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        ctx = charging_contexts.get(cid)
        if ctx and ctx.get("source_label"):
            source = ctx["source_label"]
        elif consumption_mode == "profile_spec":
            source = "Hausprofil (profile_spec)"
        elif logged_day:
            source = "geloggt (historischer Tag)"
        else:
            source_key = consumer.get("daily_target_source", "config")
            source_labels = {
                "config": "config.json",
                "historical": "historical (Profil)",
                "loxone": "loxone",
                "loxone_remaining_hours": "loxone (Sollstunden)",
                "thermal": "thermal (RC-Modell)",
                "thermal_annual": "thermal_annual (HDD-Tagesziel)",
            }
            source = source_labels.get(source_key, source_key)
        details.append({
            "id": cid,
            "name": consumer["name"],
            "target_kwh": round(float(targets.get(cid, 0.0)), 3),
            "source": source,
        })
    return details


def build_baseline_targets_detail(optimization_matrix: list) -> list[dict]:
    """
    Ermittelt die pro Verbraucher in der Baseline enthaltene Tagesenergie.
    Historisch: geloggte Summen im Gesamtverbrauchs-Stundenprofil.
    Echtzeit: Summe der stündlichen Flex-Profile (flexible_consumer_profiles.csv).
    """
    if not optimization_matrix:
        return []
    consumption_mode = optimization_matrix[0].get("consumption_mode")
    logged_day = consumption_mode == "logged_day"
    profile_spec = consumption_mode == "profile_spec"
    consumers = config.get_flexible_consumers(optimizer_only=True)
    details = []
    if logged_day or profile_spec:
        row_date = optimization_matrix[0].get("date")
        from data import consumer_targets
        totals = consumer_targets.resolve_historical_consumer_daily_targets(row_date)
        if profile_spec:
            source = "Hausprofil (profile_spec, cons_data Referenz)"
        else:
            source = "geloggt (Gesamtverbrauchs-Stundenprofil)"
        for consumer in consumers:
            cid = consumer["id"]
            details.append({
                "id": cid,
                "name": consumer["name"],
                "target_kwh": round(float(totals.get(cid, 0.0)), 3),
                "source": source,
            })
        return details
    flex_sums = {consumer["id"]: 0.0 for consumer in consumers}
    for row in optimization_matrix:
        flex = row.get("expected_flex_kw") or {}
        for cid in flex_sums:
            flex_sums[cid] += float(flex.get(cid, 0.0) or 0.0)
    has_profile_flex = any(v > 0 for v in flex_sums.values())
    source = (
        "Verbrauchsprofil (flexible_consumer_profiles.csv)"
        if has_profile_flex
        else "Gesamtprofil (total_consumption_profiles.csv, nicht aufgeteilt)"
    )
    for consumer in consumers:
        cid = consumer["id"]
        details.append({
            "id": cid,
            "name": consumer["name"],
            "target_kwh": round(flex_sums.get(cid, 0.0), 3),
            "source": source,
        })
    return details


def resolve_baseload_kwh(optimization_matrix: list) -> float:
    """Summiert die Grundlast (kWh) über den Simulationshorizont."""
    if not optimization_matrix:
        return 0.0
    return round(
        sum(float(row.get("expected_p_act", 0.0) or 0.0) for row in optimization_matrix),
        3,
    )


def build_energy_comparison_detail(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
    matched_flex_kwh: dict[str, float] | None = None,
) -> list[dict]:
    """Kombiniert Profil-Baseline, Ziel-Baseline und Optimierung je Verbraucher inkl. Grundlast."""
    baseload_kwh = resolve_baseload_kwh(optimization_matrix)
    consumption_mode = (
        optimization_matrix[0].get("consumption_mode") if optimization_matrix else None
    )
    if consumption_mode == "profile_spec":
        baseload_source = "Hausprofil (profile_spec)"
    elif consumption_mode == "logged_day":
        baseload_source = "geloggt (historischer Tag)"
    else:
        baseload_source = "Verbrauchsprofil (consumption_profiles.csv)"
    baseline_by_id = {
        item["id"]: item for item in build_baseline_targets_detail(optimization_matrix)
    }
    optimized_by_id = {
        item["id"]: item
        for item in build_applied_targets_detail(optimization_matrix, consumer_daily_targets_kwh)
    }
    matched_flex = matched_flex_kwh or {}
    rows = [{
        "name": "Grundlast",
        "baseline_kwh": baseload_kwh,
        "matched_baseline_kwh": baseload_kwh,
        "optimization_kwh": baseload_kwh,
        "optimization_source": baseload_source,
    }]
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        base = baseline_by_id.get(cid, {})
        opt = optimized_by_id.get(cid, {})
        rows.append({
            "name": consumer["name"],
            "baseline_kwh": base.get("target_kwh", 0.0),
            "matched_baseline_kwh": matched_flex.get(cid, opt.get("target_kwh", 0.0)),
            "optimization_kwh": opt.get("target_kwh", 0.0),
            "optimization_source": opt.get("source", ""),
        })
    return rows
