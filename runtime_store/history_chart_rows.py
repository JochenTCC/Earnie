"""Chart-row helpers for history_timeline (Ist-Log → Chart-/Tabellenzeilen)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import config
from data.live_consumption import is_dead_telemetry_snapshot
from data.planning_window import align_to_planning_timezone
from optimizer import battery as bat
from optimizer.consumer_power import uses_pv_follow
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from optimizer.simulation import flexible_consumer_power_kw
from optimizer.targets import (
    consumer_column_name,
    consumer_immediate_charge_column_name,
    consumer_pv_follow_column_name,
)
from settings.flexible_consumers import charging_context_lookup, flex_kw_lookup

from . import optimization_history
from .soc_plausibility import sanitize_soc_reading

# Same values as history_timeline public constants (avoid circular import).
CHART_IST_BATTERY_KW_COLUMN = "Ist Batterie-Leistung (kW)"
PV_IST_COLUMN = "PV-Ist (kW)"
SLOT_PRESENT = "present"
SLOT_HELD = "held"
SLOT_MISSING = "missing"


def _format_slot_time(slot_start: datetime, *, include_date: bool = False) -> str:
    if include_date:
        return slot_start.strftime("%d.%m. %H:%M")
    return slot_start.strftime("%H:%M")


def _align_log_timestamp(moment: datetime) -> datetime:
    return align_to_planning_timezone(moment, config.get_planning_timezone())


def _parse_completed_at(entry: dict[str, Any]) -> datetime | None:
    text = entry.get("completed_at")
    parsed: datetime | None
    if isinstance(text, datetime):
        parsed = text
    elif text:
        try:
            parsed = datetime.fromisoformat(str(text))
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        written = entry.get("written_at")
        if not written:
            return None
        try:
            parsed = datetime.fromisoformat(str(written))
        except ValueError:
            return None
    return _align_log_timestamp(parsed)


def _coerce_slot_start(slot_start: datetime) -> datetime:
    """Slot-Schlüssel für Log-Lookup (aware, Planungs-TZ)."""
    if slot_start.tzinfo is None:
        return quarter_hour_slot_start(_align_log_timestamp(slot_start))
    return quarter_hour_slot_start(slot_start)


def _index_entries_by_slot(
    entries: list[dict[str, Any]],
) -> dict[datetime, dict[str, Any]]:
    by_slot: dict[datetime, dict[str, Any]] = {}
    for entry in entries:
        completed = _parse_completed_at(entry)
        if completed is None:
            continue
        slot = quarter_hour_slot_start(completed)
        existing = by_slot.get(slot)
        if existing is None:
            by_slot[slot] = entry
            continue
        existing_at = _parse_completed_at(existing)
        if existing_at is None or completed > existing_at:
            by_slot[slot] = entry
    return by_slot


def _pv_forecast_kw_from_entry(entry: dict[str, Any]) -> float:
    return float(entry.get("forecast_pv_kw", 0.0) or 0.0)


def _chart_snapshot(entry: dict[str, Any]) -> dict[str, Any]:
    """Consumption snapshot for chart rows; dead all-zero telemetry is ignored."""
    snapshot = entry.get("consumption_snapshot") or {}
    if is_dead_telemetry_snapshot(snapshot):
        return {}
    return snapshot


def _power_kw_from_entry(entry: dict[str, Any]) -> tuple[float, float, float]:
    snapshot = _chart_snapshot(entry)
    pv = snapshot.get("pv_kw")
    if pv is None:
        pv = entry.get("forecast_pv_kw", 0.0)
    baseload = snapshot.get("baseload_kw")
    if baseload is None:
        baseload = entry.get("forecast_consumption_kw", 0.0)
    battery_plan = entry.get("battery_plan_kw")
    if battery_plan is None:
        mode = int(entry.get("mode", bat.MODE_AUTOMATIK))
        target_power = float(entry.get("target_power_kw", 0.0) or 0.0)
        if mode in (bat.MODE_ZWANGS_LADEN, bat.MODE_ZWANGS_ENTLADEN):
            battery_plan = target_power if mode == bat.MODE_ZWANGS_LADEN else -target_power
        else:
            battery_plan = 0.0
    return float(pv), float(baseload), float(battery_plan)


def _chart_battery_kw_from_snapshot(snapshot: dict[str, Any]) -> float | None:
    """Loxone ``battery_kw`` (negativ = laden) → Chart-Vorzeichen (positiv = laden)."""
    raw = snapshot.get("battery_kw")
    if raw is None:
        return None
    return round(-float(raw), 3)


def _pv_kw_for_balance(row: dict[str, Any]) -> float:
    """PV für Energiebilanz: Ist aus Log-Snapshot, sonst Prognose."""
    if PV_IST_COLUMN in row:
        raw = row.get(PV_IST_COLUMN)
        if raw is not None:
            try:
                ist = float(raw)
                if not math.isnan(ist):
                    return ist
            except (TypeError, ValueError):
                pass
    return float(row.get("PV-Prognose (kW)", 0.0) or 0.0)


def _netzbezug_kw_from_entry(entry: dict[str, Any], row: dict[str, Any]) -> float:
    """Netzbezug: gemessenes grid_kw aus consumption_snapshot, sonst Bilanz aus der Zeile."""
    snapshot = _chart_snapshot(entry)
    grid = snapshot.get("grid_kw")
    if grid is not None:
        return round(float(grid), 2)
    return round(
        float(row["Verbrauch-Prognose (kW)"])
        + flexible_consumer_power_kw(row)
        - _pv_kw_for_balance(row)
        + float(row["Geplante Batterie-Aktion (kW)"]),
        2,
    )


def _flex_dict_has_consumer(flex: dict[str, Any] | None, consumer: dict[str, Any]) -> bool:
    if not flex:
        return False
    return str(consumer["id"]) in flex


def _consumer_is_measured(measured_ids: Any, consumer: dict[str, Any]) -> bool:
    """True if measured_ids lists the canonical consumer id."""
    if measured_ids is None:
        return True
    return str(consumer["id"]) in measured_ids


def _consumer_kw_from_entry(
    entry: dict[str, Any],
    consumer: dict[str, Any],
) -> float | None:
    """Flex-Leistung für Chart/Tabelle im Produktiv-Log — Ist, nicht MILP-Soll."""
    measured_ids = entry.get("flex_measured_ids")
    if not _consumer_is_measured(measured_ids, consumer):
        return None

    snapshot = _chart_snapshot(entry)
    flex_kw = snapshot.get("flex_kw") or {}
    if _flex_dict_has_consumer(flex_kw, consumer):
        return float(flex_kw_lookup(flex_kw, consumer))
    live = entry.get("flex_live_kw") or {}
    if _flex_dict_has_consumer(live, consumer):
        return float(flex_kw_lookup(live, consumer))
    if measured_ids is not None:
        return None
    return 0.0


def _immediate_charge_flags_from_entry(entry: dict[str, Any] | None) -> dict[str, int]:
    """Sofort-Laden-Flags aus dem gespeicherten charging_contexts (falls vorhanden)."""
    contexts = (entry or {}).get("charging_contexts") or {}
    flags: dict[str, int] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        ctx = charging_context_lookup(contexts, consumer)
        flags[consumer_immediate_charge_column_name(consumer)] = (
            1 if ctx.get("immediate_charge") else 0
        )
    return flags


def _feed_in_price_cent_from_entry(entry: dict[str, Any] | None) -> float:
    """Einspeisevergütung aus k_push_act im Log, sonst fixer Config-Fallback."""
    if entry is not None and entry.get("k_push_act") is not None:
        return round(float(entry["k_push_act"]), 4)
    return round(config.get_push_price_cent(), 4)


def _import_price_cent_from_entry(
    entry: dict[str, Any],
    *,
    slot_start: datetime | None = None,
) -> float:
    """
    Bezugspreis (Cent/kWh) für Chart/Tabelle aus dem Produktiv-Log.

    Neu: market_price_cent ist Retail (k_act); optional epex_price_cent.
    Legacy: market_price_cent war EPEX (price_buy) — dann auf Retail umrechnen.
    """
    raw = float(entry.get("market_price_cent", 0.0) or 0.0)
    if entry.get("epex_price_cent") is not None:
        return round(raw, 4)

    k_push = entry.get("k_push_act")
    if k_push is None:
        return round(raw, 4)

    from data.feed_in_prices import resolve_k_push_act
    from data.market_prices import epex_to_brutto_cent

    expected_push = resolve_k_push_act(
        raw,
        config.get_feed_in_settings(),
        slot_datetime=slot_start,
    )
    if abs(float(expected_push) - float(k_push)) <= 0.05:
        return round(float(epex_to_brutto_cent(raw)), 4)
    return round(raw, 4)


def _append_milp_table_columns(row: dict[str, Any], entry: dict[str, Any] | None) -> None:
    """
    Spalten, die nur in MILP-Chart-Zeilen vorkommen — für die Tabelle mit Defaults befüllen.

    Einspeisevergütung: k_push_act aus dem Produktiv-Lauf, sonst Config-Fallback.
    sofort_laden: aus charging_contexts des Produktiv-Laufs, sonst 0.
    """
    row["Einspeisevergütung (Cent/kWh)"] = _feed_in_price_cent_from_entry(entry)
    row.update(_immediate_charge_flags_from_entry(entry))


def entry_to_chart_row(
    entry: dict[str, Any],
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    """Baut eine Chart-Zeile aus einem Produktiv-Durchlauf."""
    mode = int(entry.get("mode", bat.MODE_AUTOMATIK))
    target_power = float(entry.get("target_power_kw", 0.0) or 0.0)
    _, baseload, battery_plan = _power_kw_from_entry(entry)
    snapshot = _chart_snapshot(entry)
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start, include_date=include_date),
        "Strompreis (Cent/kWh)": _import_price_cent_from_entry(
            entry, slot_start=slot_start
        ),
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": round(_pv_forecast_kw_from_entry(entry), 3),
        "Verbrauch-Prognose (kW)": round(baseload, 3),
        "Geplante Batterie-Aktion (kW)": round(battery_plan, 3),
        "Simulierter SoC (%)": round(float(entry.get("soc_percent", 0.0) or 0.0), 1),
        "Steuerbefehl": bat.steuerbefehl_for_mode(mode, target_power),
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        flex_kw = _consumer_kw_from_entry(entry, consumer)
        row[consumer_column_name(consumer)] = (
            round(flex_kw, 2) if flex_kw is not None else None
        )
        if uses_pv_follow(consumer):
            pv_follow_map = entry.get("consumer_pv_follow") or {}
            row[consumer_pv_follow_column_name(consumer)] = int(
                pv_follow_map.get(cid, 0) or 0
            )
    if snapshot.get("pv_kw") is not None:
        row[PV_IST_COLUMN] = round(float(snapshot["pv_kw"]), 3)
    row["Netzbezug (kW)"] = _netzbezug_kw_from_entry(entry, row)
    ist_battery = _chart_battery_kw_from_snapshot(snapshot)
    if ist_battery is not None:
        row[CHART_IST_BATTERY_KW_COLUMN] = ist_battery
    _append_milp_table_columns(row, entry)
    return row


def _zero_flex_power(row: dict[str, Any]) -> None:
    """Hold-Forward gilt für SoC/Preis — flexible Verbraucher bleiben aus."""
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        row[consumer_column_name(consumer)] = 0.0
        if uses_pv_follow(consumer):
            row[consumer_pv_follow_column_name(consumer)] = 0
    baseload = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
    battery_plan = float(row.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
    row["Netzbezug (kW)"] = round(
        baseload - _pv_kw_for_balance(row) + battery_plan,
        2,
    )


def _hold_forward_row(
    previous: dict[str, Any],
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    row = dict(previous)
    row["slot_datetime"] = slot_start
    row["Uhrzeit"] = _format_slot_time(slot_start, include_date=include_date)
    row.pop(CHART_IST_BATTERY_KW_COLUMN, None)
    row.pop(PV_IST_COLUMN, None)
    _zero_flex_power(row)
    return row


def _missing_chart_row(
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    """Leere Zeile für fehlende Log-Slots (S-2, Spec v0.6.1 — kein Hold-Forward)."""
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start, include_date=include_date),
        "Strompreis (Cent/kWh)": None,
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": None,
        PV_IST_COLUMN: None,
        "Verbrauch-Prognose (kW)": None,
        "Geplante Batterie-Aktion (kW)": None,
        "Netzbezug (kW)": None,
        "Simulierter SoC (%)": None,
        "Steuerbefehl": "",
        "Einspeisevergütung (Cent/kWh)": None,
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        row[consumer_column_name(consumer)] = None
        if uses_pv_follow(consumer):
            row[consumer_pv_follow_column_name(consumer)] = None
        row[consumer_immediate_charge_column_name(consumer)] = None
    return row


def _empty_chart_row(
    slot_start: datetime,
    *,
    include_date: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slot_datetime": slot_start,
        "Uhrzeit": _format_slot_time(slot_start, include_date=include_date),
        "Strompreis (Cent/kWh)": 0.0,
        "Preis extrapoliert": False,
        "PV-Prognose (kW)": 0.0,
        "Verbrauch-Prognose (kW)": 0.0,
        "Geplante Batterie-Aktion (kW)": 0.0,
        "Netzbezug (kW)": 0.0,
        "Simulierter SoC (%)": 0.0,
        "Steuerbefehl": bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0),
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        row[consumer_column_name(consumer)] = 0.0
        if uses_pv_follow(consumer):
            row[consumer_pv_follow_column_name(consumer)] = 0
    _append_milp_table_columns(row, None)
    return row


def _battery_kw_for_soc_row(row: dict[str, Any]) -> float:
    ist = row.get(CHART_IST_BATTERY_KW_COLUMN)
    if ist is not None:
        try:
            return float(ist)
        except (TypeError, ValueError):
            pass
    plan = row.get("Geplante Batterie-Aktion (kW)")
    if plan is not None:
        try:
            return float(plan)
        except (TypeError, ValueError):
            pass
    return 0.0


def _sanitize_history_soc_rows(
    rows: list[dict[str, Any]],
    qualities: list[str],
) -> list[dict[str, Any]]:
    """Replace implausible Produktiv-Log SoC spikes using battery power integration."""
    if not rows:
        return rows
    battery_params = config.get_battery_params()
    prev_soc: float | None = None
    last_raw_reported: float | None = None
    consecutive_same_reported = 0
    sanitized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row = dict(row)
        reported = row.get("Simulierter SoC (%)")
        if reported is None or qualities[index] != SLOT_PRESENT:
            sanitized.append(row)
            continue
        raw_reported = float(reported)
        if last_raw_reported is not None and raw_reported == last_raw_reported:
            consecutive_same_reported += 1
        else:
            consecutive_same_reported = 1
        last_raw_reported = raw_reported
        soc_value, corrected = sanitize_soc_reading(
            prev_soc,
            raw_reported,
            _battery_kw_for_soc_row(row),
            battery_params,
            consecutive_same_reported=consecutive_same_reported,
        )
        if corrected:
            row["Simulierter SoC (%)"] = soc_value
        prev_soc = float(row["Simulierter SoC (%)"])
        sanitized.append(row)
    return sanitized


def _sanitize_dead_telemetry_rows(
    rows: list[dict[str, Any]],
    qualities: tuple[str, ...] | list[str],
    by_slot: dict[datetime, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Hold-forward load/flex when log slot exists but live meters returned all zeros."""
    last_good: dict[str, Any] | None = None
    sanitized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row = dict(row)
        if qualities[index] == SLOT_PRESENT:
            slot_start = row.get("slot_datetime")
            entry = (
                by_slot.get(_coerce_slot_start(slot_start))
                if slot_start is not None
                else None
            )
            snapshot = (entry or {}).get("consumption_snapshot") or {}
            if is_dead_telemetry_snapshot(snapshot):
                if last_good is not None and float(row.get("Verbrauch-Prognose (kW)") or 0) <= 0:
                    row["Verbrauch-Prognose (kW)"] = last_good["Verbrauch-Prognose (kW)"]
                    for consumer in config.get_flexible_consumers(optimizer_only=True):
                        col = consumer_column_name(consumer)
                        if float(row.get(col) or 0) <= 0 and last_good.get(col):
                            row[col] = last_good[col]
                    row["Netzbezug (kW)"] = _netzbezug_kw_from_entry(entry or {}, row)
            else:
                last_good = row
        sanitized.append(row)
    return sanitized


def _build_rows_for_slot_starts(
    slot_starts: tuple[datetime, ...] | list[datetime],
    *,
    include_date: bool = False,
    hold_forward: bool = True,
) -> tuple[list[dict[str, Any]], tuple[str, ...], int, int, int, dict[datetime, dict[str, Any]]]:
    if not slot_starts:
        return [], (), 0, 0, 0, {}
    starts = tuple(slot_starts)
    window_start = _coerce_slot_start(starts[0])
    window_end = _coerce_slot_start(starts[-1]) + timedelta(minutes=QUARTER_HOUR_MINUTES)
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    by_slot = _index_entries_by_slot(entries)
    rows: list[dict[str, Any]] = []
    qualities: list[str] = []
    present = held = missing = 0
    last_row: dict[str, Any] | None = None
    for slot_start in starts:
        slot_key = _coerce_slot_start(slot_start)
        entry = by_slot.get(slot_key)
        if entry is not None:
            row = entry_to_chart_row(entry, slot_key, include_date=include_date)
            present += 1
            last_row = row
            qualities.append(SLOT_PRESENT)
        elif hold_forward and last_row is not None:
            row = _hold_forward_row(last_row, slot_key, include_date=include_date)
            held += 1
            qualities.append(SLOT_HELD)
        elif hold_forward:
            row = _empty_chart_row(slot_key, include_date=include_date)
            missing += 1
            qualities.append(SLOT_MISSING)
        else:
            row = _missing_chart_row(slot_key, include_date=include_date)
            missing += 1
            qualities.append(SLOT_MISSING)
        rows.append(row)
    rows = _sanitize_dead_telemetry_rows(rows, qualities, by_slot)
    rows = _sanitize_history_soc_rows(rows, qualities)
    return rows, tuple(qualities), present, held, missing, by_slot
