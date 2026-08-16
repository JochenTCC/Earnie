"""Auflösung von Ladekontexten (Loxone, Config, Historie)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import config
from integrations import loxone_client
from optimizer.charging_schedule import (
    _facade_loxone_ready_raw,
    charging_deadline_after,
    charging_schedule_enabled,
    config_day_schedule,
    deadline_from_ready_hour,
    matrix_charging_anchor,
    matrix_slot_datetime,
    next_scheduled_availability,
    parse_loxone_ready_by_time,
    resolve_charging_deadline,
    _window_start_for_day,
)
from settings.ehal_marker_resolve import marker_sens_evcs_connected
from settings.flexible_consumers import flex_kw_lookup
from optimizer.charging_urgent import urgent_min_kwh_from_soc


def _cc():
    """Facade module — tests patch symbols on optimizer.charging_context."""
    from optimizer import charging_context as cc

    return cc


def suppresses_live_charging_output(ctx: dict | None) -> bool:
    """Kein Loxone-Sollwert und keine Buchung: Prognose bei Abwesenheit ohne Anschluss."""
    if not ctx:
        return False
    return bool(ctx.get("anticipated") and not ctx.get("plugged_in"))


def resolve_absent_availability(
    horizon_start: datetime,
    consumer: dict,
    *,
    ready_raw: str | float | None = None,
    open_cycle_deadline: datetime | None = None,
) -> datetime | None:
    """
    Ladebeginn bei Abwesenheit: offenes Übernacht-Fenster oder nächster Termin.

    Verspätete Rückkehr am selben Tag (Slot vorbei, Auto noch abgehängt) gilt nicht
    als „jetzt verfügbar“ — es wird der nächste car_available_from_hour verwendet.

    open_cycle_deadline: Latch aus flexible_consumers_state — kurzes Unplug vor
    FertigUm hält den laufenden Ladezyklus offen (available_from = jetzt).
    """
    from .charging_session import deadline_reached

    if open_cycle_deadline is not None and not deadline_reached(
        horizon_start, open_cycle_deadline
    ):
        return horizon_start
    for day_offset in (0, -1):
        day = horizon_start.date() + timedelta(days=day_offset)
        window_start = _window_start_for_day(consumer, day, reference=horizon_start)
        if window_start is None or window_start > horizon_start:
            continue
        deadline, _ = resolve_charging_deadline(
            consumer,
            window_start,
            window_start,
            ready_raw=ready_raw,
        )
        if deadline is None or horizon_start >= deadline:
            continue
        if window_start.date() < horizon_start.date():
            today_from = _window_start_for_day(
                consumer, horizon_start.date(), reference=horizon_start
            )
            if today_from is not None and horizon_start >= today_from:
                continue
            # FertigUm parsed from yesterday's window_start can push the overnight
            # deadline into daytime (e.g. "Morgen, 11:00" → 11:00). Only treat the
            # overnight cycle as still open before the *config* ready_by.
            config_deadline = charging_deadline_after(window_start, consumer)
            if config_deadline is not None and horizon_start >= config_deadline:
                continue
            return horizon_start
    return next_scheduled_availability(horizon_start, consumer)


def _loxone_inactive_context(source_label: str) -> dict:
    return {
        "active": False,
        "plugged_in": False,
        "deadline": None,
        "target_kwh": 0.0,
        "use_time_window": False,
        "source_label": source_label,
    }


def _loxone_plugged_in_complete_context() -> dict:
    """Angeschlossen, Ladeziel erreicht (Ist-SOC) — FertigUm wird nicht verwendet."""
    return {
        "active": False,
        "plugged_in": True,
        "deadline": None,
        "target_kwh": 0.0,
        "use_time_window": False,
        "source_label": "loxone (angeschlossen, Ladung abgeschlossen — FertigUm ignoriert)",
    }


def _plugged_in_fulfilled_context() -> dict:
    """Angeschlossen, Sessionziel in diesem Plug-Zyklus bereits erfüllt."""
    return {
        "active": False,
        "plugged_in": True,
        "deadline": None,
        "target_kwh": 0.0,
        "use_time_window": False,
        "source_label": (
            "session (angeschlossen, Ladeziel im Plug-Zyklus erfüllt — FertigUm ignoriert)"
        ),
    }


def _loxone_absent_forecast_context(
    consumer: dict,
    horizon_start: datetime,
    *,
    open_cycle_deadline: datetime | None = None,
) -> dict:
    ready_raw = _facade_loxone_ready_raw(consumer)
    loxone_deadline = parse_loxone_ready_by_time(ready_raw, horizon_start)
    if loxone_deadline is None:
        return _loxone_inactive_context(
            "loxone (abwesend, keine aktive Fertigstellungszeit in Loxone)"
        )
    available_from = resolve_absent_availability(
        horizon_start,
        consumer,
        ready_raw=ready_raw,
        open_cycle_deadline=open_cycle_deadline,
    )
    if available_from is None:
        return _loxone_inactive_context(
            "loxone (abwesend, kein car_available_from_hour in Config)"
        )
    if loxone_deadline <= available_from:
        return _loxone_inactive_context(
            "loxone (abwesend, keine gültige Fertigstellungszeit)"
        )
    day_sched = config_day_schedule(consumer, available_from)
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    limit_soc = _cc().resolve_get_evcs_limit_soc(consumer)
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer,
        day_sched.get("daily_rest_soc"),
        capacity_kwh=capacity_kwh,
        limit_soc_percent=limit_soc,
    )
    if target_kwh is None or target_kwh <= 0:
        return _loxone_inactive_context(
            "loxone (abwesend, kein Ladeziel aus daily_rest_soc)"
        )
    return {
        "active": True,
        "plugged_in": False,
        "anticipated": True,
        "available_from": available_from,
        "deadline": loxone_deadline,
        "target_kwh": round(target_kwh, 3),
        "use_time_window": False,
        "source_label": "loxone (abwesend, Prognose + FertigUm Loxone)",
    }


def fetch_loxone_charging_context(
    consumer: dict,
    horizon_start: datetime,
    *,
    open_cycle_deadline: datetime | None = None,
) -> dict:
    sched = consumer.get("charging_schedule") or {}
    plug_name = marker_sens_evcs_connected(consumer)
    plugged_val = (
        loxone_client.fetch_loxone_generic_value(plug_name) if plug_name else None
    )
    plugged_in = plugged_val is not None and int(round(float(plugged_val))) == 1
    if not plugged_in:
        if sched.get("forecast_when_absent"):
            return _loxone_absent_forecast_context(
                consumer,
                horizon_start,
                open_cycle_deadline=open_cycle_deadline,
            )
        return _loxone_inactive_context("loxone (nicht angeschlossen)")
    if _cc().loxone_reports_charge_complete(consumer):
        return _loxone_plugged_in_complete_context()
    ready_raw = _facade_loxone_ready_raw(consumer)
    deadline = parse_loxone_ready_by_time(ready_raw, horizon_start)
    soc_val = _cc().fetch_loxone_actual_soc_percent(consumer)
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    limit_soc = _cc().resolve_get_evcs_limit_soc(consumer)
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer,
        soc_val,
        capacity_kwh=capacity_kwh,
        limit_soc_percent=limit_soc,
    )
    soc_min_immediate = _cc().resolve_get_evcs_soc_min_immediate(consumer)
    urgent_min_kwh = urgent_min_kwh_from_soc(
        consumer,
        actual_soc=soc_val,
        soc_min_immediate=soc_min_immediate,
        capacity_kwh=capacity_kwh,
    )
    return {
        "active": True,
        "plugged_in": True,
        "deadline": deadline,
        "target_kwh": round(target_kwh, 3) if target_kwh is not None else None,
        "use_time_window": False,
        "source_label": "loxone (angeschlossen, SOC → kWh)",
        "soc_min_immediate": soc_min_immediate,
        "urgent_min_kwh": round(urgent_min_kwh, 3),
    }


def historical_charging_context(
    consumer: dict,
    matrix: list,
    consumer_daily_targets_kwh: dict | None,
    horizon_start: datetime,
    *,
    realtime: bool,
) -> dict:
    from . import targets as optimizer_targets

    charging_anchor = matrix_charging_anchor(matrix)
    schedule_ref = charging_anchor or horizon_start
    day_sched = config_day_schedule(consumer, schedule_ref)
    targets = optimizer_targets.resolve_horizon_consumer_targets_kwh(
        matrix, consumer_daily_targets_kwh
    )
    target_kwh = float(targets.get(consumer["id"], 0.0))
    if charging_anchor is not None:
        deadline = charging_anchor
    else:
        deadline = deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
    if realtime:
        source_label = "historical (Profil 24h-Horizont + Config-Zeitfenster)"
    else:
        source_label = "historisch (Config-Zeitfenster + Log-Ziel)"
    return {
        "active": target_kwh > 0,
        "deadline": deadline,
        "target_kwh": round(target_kwh, 3) if target_kwh > 0 else 0.0,
        "use_time_window": True,
        "config_day_schedule": day_sched,
        "source_label": source_label,
    }


def _config_path_with_plugged_in(
    result: dict,
    consumer: dict,
    sched: dict,
    horizon_start: datetime,
    ready_raw: str | float | None,
    *,
    open_cycle_deadline: datetime | None = None,
) -> dict:
    """Attach Loxone plugged_in; suppress live output when absent (anticipated)."""
    plug_name = marker_sens_evcs_connected(consumer)
    if not plug_name:
        return result
    plugged_val = loxone_client.fetch_loxone_generic_value(plug_name)
    plugged_in = plugged_val is not None and int(round(float(plugged_val))) == 1
    if plugged_in:
        out = dict(result)
        out["plugged_in"] = True
        return out
    if not sched.get("forecast_when_absent"):
        return _loxone_inactive_context("config (nicht angeschlossen)")
    out = dict(result)
    out["plugged_in"] = False
    out["anticipated"] = True
    available_from = resolve_absent_availability(
        horizon_start,
        consumer,
        ready_raw=ready_raw,
        open_cycle_deadline=open_cycle_deadline,
    )
    if available_from is not None:
        out["available_from"] = available_from
    if "FertigUm" in str(out.get("source_label") or ""):
        out["source_label"] = "config.json (abwesend, Prognose + FertigUm Loxone)"
    else:
        out["source_label"] = "config.json (abwesend, Prognose)"
    return out


def _config_path_apply_live_ist_soc(
    out: dict,
    consumer: dict,
    *,
    capacity_kwh: float | None,
    limit_soc: float,
    from_loxone: bool,
) -> dict:
    """Plugged-in config path: energy from Ist-SOC (not daily_rest_soc forecast)."""
    if out.get("plugged_in") is not True:
        return out
    if _cc().loxone_reports_charge_complete(consumer):
        return _loxone_plugged_in_complete_context()
    soc_val = _cc().fetch_loxone_actual_soc_percent(consumer)
    if soc_val is None:
        return out
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer,
        soc_val,
        capacity_kwh=capacity_kwh,
        limit_soc_percent=limit_soc,
    )
    updated = dict(out)
    updated["target_kwh"] = round(target_kwh, 3) if target_kwh is not None else None
    if from_loxone:
        updated["source_label"] = "config.json (Ist-SOC → kWh, FertigUm Loxone)"
    else:
        updated["source_label"] = "config.json (Ist-SOC → kWh)"
    return updated


def _resolve_config_path_charging_context(
    consumer: dict,
    sched: dict,
    horizon_start: datetime,
    *,
    open_cycle_deadline: datetime | None = None,
) -> dict:
    """Config daily_target_source: rest-SoC + FertigUm/Ist-SOC overlays."""
    day_sched = config_day_schedule(consumer, horizon_start)
    rest_soc = day_sched.get("daily_rest_soc")
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    limit_soc = _cc().resolve_get_evcs_limit_soc(consumer)
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer,
        rest_soc,
        capacity_kwh=capacity_kwh,
        limit_soc_percent=limit_soc,
    )
    config_deadline = deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
    ready_raw = _facade_loxone_ready_raw(consumer)
    deadline, from_loxone = resolve_charging_deadline(
        consumer, horizon_start, horizon_start, ready_raw=ready_raw
    )
    # FertigUm overrides config ready_by_hour; drop config hour-window so later
    # deadlines (e.g. 14:00) are actually eligible for planning/charging.
    use_time_window = not from_loxone
    if from_loxone:
        source_label = "config.json (daily_rest_soc → kWh, FertigUm Loxone)"
    else:
        source_label = "config.json (daily_rest_soc → kWh)"
        deadline = config_deadline
    result = {
        "active": True,
        "deadline": deadline,
        "target_kwh": round(target_kwh, 3) if target_kwh is not None else None,
        "use_time_window": use_time_window,
        "config_day_schedule": day_sched,
        "source_label": source_label,
    }
    out = _config_path_with_plugged_in(
        result,
        consumer,
        sched,
        horizon_start,
        ready_raw,
        open_cycle_deadline=open_cycle_deadline,
    )
    return _config_path_apply_live_ist_soc(
        out,
        consumer,
        capacity_kwh=capacity_kwh,
        limit_soc=limit_soc,
        from_loxone=from_loxone,
    )


def resolve_charging_context(
    consumer: dict,
    matrix: list,
    consumer_daily_targets_kwh: dict | None,
    logged_simulation: bool,
    *,
    open_cycle_deadline: datetime | None = None,
) -> dict:
    sched = consumer.get("charging_schedule")
    if not sched or not sched.get("enabled"):
        return {"active": True, "deadline": None, "target_kwh": None, "use_time_window": False}
    horizon_start = matrix_slot_datetime(matrix, 0)
    target_source = consumer.get("daily_target_source", "config")
    if logged_simulation or target_source == "historical":
        return historical_charging_context(
            consumer,
            matrix,
            consumer_daily_targets_kwh,
            horizon_start,
            realtime=not logged_simulation,
        )
    if target_source == "loxone":
        return fetch_loxone_charging_context(
            consumer,
            horizon_start,
            open_cycle_deadline=open_cycle_deadline,
        )
    return _resolve_config_path_charging_context(
        consumer,
        sched,
        horizon_start,
        open_cycle_deadline=open_cycle_deadline,
    )


def _load_consumer_state_json() -> dict:
    try:
        from runtime_store.persist_paths import consumer_state_file

        path = consumer_state_file()
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _load_plug_cycle_fulfilled_flags() -> dict[str, bool]:
    """Leichtgewichtiger Read des Plug-Zyklus-Latch aus flexible_consumers_state."""
    raw = _load_consumer_state_json()
    fulfilled = raw.get("plug_cycle_fulfilled") or {}
    if not isinstance(fulfilled, dict):
        return {}
    return {str(cid): True for cid, flag in fulfilled.items() if flag}


def _load_open_charging_deadlines() -> dict[str, str]:
    """Read open plug-cycle deadlines (survive brief unplug until FertigUm)."""
    from .charging_session import sync_open_charging_deadlines

    raw = _load_consumer_state_json()
    open_raw = raw.get("open_charging_deadlines") or {}
    if not isinstance(open_raw, dict):
        open_raw = {}
    fulfilled_raw = raw.get("plug_cycle_fulfilled") or {}
    fulfilled = {
        str(cid): True
        for cid, flag in fulfilled_raw.items()
        if isinstance(fulfilled_raw, dict) and flag
    }
    return sync_open_charging_deadlines(
        {str(cid): str(dl) for cid, dl in open_raw.items() if dl},
        {},
        plug_cycle_fulfilled=fulfilled,
        now=datetime.now(),
    )


def apply_plug_cycle_fulfilled_contexts(
    contexts: dict[str, dict],
    fulfilled: dict[str, bool] | None,
) -> dict[str, dict]:
    """Deaktiviert Ladekontext solange Plug-Zyklus bereits erfüllt und angesteckt."""
    if not fulfilled:
        return contexts
    out = dict(contexts)
    for cid, ctx in contexts.items():
        if not fulfilled.get(cid):
            continue
        if ctx.get("plugged_in") is not True:
            continue
        if ctx.get("immediate_charge"):
            continue
        out[cid] = _plugged_in_fulfilled_context()
    return out


def resolve_charging_contexts(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
    *,
    live_flex_kw: dict[str, float] | None = None,
    consumers: list | None = None,
    plug_cycle_fulfilled: dict[str, bool] | None = None,
    open_charging_deadlines: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Ladekontext je Verbraucher mit charging_schedule für den Optimierungshorizont."""
    from . import charge_immediate as ci
    from .charging_session import drop_stale_plug_cycle_latch, parse_open_charging_deadline

    logged_simulation = bool(
        optimization_matrix
        and optimization_matrix[0].get("consumption_mode")
        in ("logged_day", "profile_spec")
    )
    active = consumers if consumers is not None else config.get_flexible_consumers(
        optimizer_only=True
    )
    horizon = len(optimization_matrix) if optimization_matrix else 24
    open_deadlines = (
        open_charging_deadlines
        if open_charging_deadlines is not None
        else _load_open_charging_deadlines()
    )
    contexts: dict[str, dict] = {}
    for consumer in active:
        if not charging_schedule_enabled(consumer):
            continue
        cid = consumer["id"]
        contexts[cid] = resolve_charging_context(
            consumer,
            optimization_matrix,
            consumer_daily_targets_kwh,
            logged_simulation,
            open_cycle_deadline=parse_open_charging_deadline(open_deadlines, cid),
        )
        live_kw = flex_kw_lookup(live_flex_kw, consumer)
        contexts[cid] = ci.enrich_context_with_immediate_charge(
            consumer,
            contexts[cid],
            live_kw=live_kw,
            horizon=horizon,
        )
    fulfilled = (
        plug_cycle_fulfilled
        if plug_cycle_fulfilled is not None
        else _load_plug_cycle_fulfilled_flags()
    )
    raw_state = _load_consumer_state_json()
    sessions = raw_state.get("charging_sessions") or {}
    if not isinstance(sessions, dict):
        sessions = {}
    fulfilled = drop_stale_plug_cycle_latch(fulfilled, contexts, sessions)
    return apply_plug_cycle_fulfilled_contexts(contexts, fulfilled)
















def serialize_charging_contexts(contexts: dict[str, dict]) -> dict[str, dict]:
    """Datetime-Felder für JSON-Logs in ISO-Strings wandeln."""
    serialized: dict[str, dict] = {}
    for cid, ctx in contexts.items():
        row = dict(ctx)
        for key in ("deadline", "available_from"):
            value = row.get(key)
            if isinstance(value, datetime):
                row[key] = value.isoformat(timespec="seconds")
        serialized[cid] = row
    return serialized


def apply_horizon_charging_limits(
    horizon_limits: dict[str, float],
    charging_contexts: dict[str, dict],
) -> dict[str, float]:
    adjusted = dict(horizon_limits)
    for cid, ctx in charging_contexts.items():
        if not ctx.get("active", True):
            adjusted[cid] = 0.0
        elif ctx.get("target_kwh") is not None:
            adjusted[cid] = round(float(ctx["target_kwh"]), 3)
    return adjusted
