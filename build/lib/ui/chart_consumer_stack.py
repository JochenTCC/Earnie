"""Gestapelte Verbraucher-Balken und Stack-Reihenfolge."""
from __future__ import annotations

from datetime import datetime

import config
import pandas as pd

from data.planning_window import UiChartWindow, normalize_hour_slot
from optimizer.appliance_schedule import (
    appliance_as_chart_consumer,
    appliance_column_name,
    appliance_kw_for_slot,
)
from optimizer.targets import (
    consumer_column_name,
    consumer_immediate_charge_column_name,
    consumer_pv_follow_column_name,
)
from ui.chart_colors import (
    COLOR_STEER_BASELINE,
    COLOR_STEER_DEFAULT,
    COLOR_STEER_ENTLADESPERRE,
    COLOR_STEER_FORCE_CHARGE,
    COLOR_STEER_FORCE_DISCHARGE,
)
from ui.chart_slot_axis import _safe_float, _safe_int_flag

_CONSUMER_BAR_OPACITY = 0.65


def _chart_flex_consumers(*, optimizer_only: bool = True) -> list[dict]:
    """Resolved flex list (config + house-profile planning merge)."""
    from simulation.engine import resolved_flexible_consumers

    scenario = config.get_resolved_runtime_settings()
    return resolved_flexible_consumers(scenario, optimizer_only=optimizer_only)


_CONSUMER_PV_FOLLOW_PATTERN = "/"


_CONSUMER_IMMEDIATE_CHARGE_PATTERN = "+"


_STACK_ORDER_BY_SA0: dict[str, tuple[str, ...]] = {}


def _consumer_bar_pattern_shapes(
    segment: pd.DataFrame,
    power_col: str,
    pv_follow_col: str | None,
    immediate_col: str | None = None,
) -> list[str]:
    """Muster je Stunde: Sofort-Laden → Karo (+), pv_follow → Schräg (/), sonst Vollfläche."""
    shapes: list[str] = []
    for _, row in segment.iterrows():
        power = _safe_float(row.get(power_col, 0.0))
        if power <= 1e-6:
            shapes.append("")
            continue
        if immediate_col and immediate_col in segment.columns:
            if _safe_int_flag(row.get(immediate_col, 0)) == 1:
                shapes.append(_CONSUMER_IMMEDIATE_CHARGE_PATTERN)
                continue
        if pv_follow_col and pv_follow_col in segment.columns:
            if _safe_int_flag(row.get(pv_follow_col, 0)) == 1:
                shapes.append(_CONSUMER_PV_FOLLOW_PATTERN)
                continue
        shapes.append("")
    return shapes


def _consumer_bar_marker(
    color: str,
    pattern_shapes: list[str],
    opacity: float,
) -> dict:
    marker: dict = {"color": color, "opacity": opacity}
    if any(shape for shape in pattern_shapes):
        # fgcolor muss sich von bgcolor unterscheiden — sonst ist die Schraffur unsichtbar.
        marker["pattern"] = dict(
            shape=pattern_shapes,
            fgcolor="rgba(255, 255, 255, 0.8)",
            bgcolor=color,
            solidity=0.35,
            fillmode="overlay",
        )
    return marker


def _chart_has_immediate_charge_bars(df: pd.DataFrame) -> bool:
    for consumer in _chart_flex_consumers():
        imm_col = consumer_immediate_charge_column_name(consumer)
        power_col = f"{consumer['name']} (kW)"
        if imm_col not in df.columns or power_col not in df.columns:
            continue
        mask = (df[imm_col].fillna(0).astype(int) == 1) & (df[power_col].fillna(0.0) > 0)
        if mask.any():
            return True
    return False


def _chart_has_pv_follow_bars(df: pd.DataFrame) -> bool:
    for consumer in _chart_flex_consumers():
        pv_col = consumer_pv_follow_column_name(consumer)
        power_col = f"{consumer['name']} (kW)"
        if pv_col not in df.columns or power_col not in df.columns:
            continue
        mask = (df[pv_col].fillna(0).astype(int) == 1) & (df[power_col].fillna(0.0) > 0)
        if mask.any():
            return True
    return False


def _is_entladesperre_command(cmd) -> bool:
    return "Entladesperre" in str(cmd)


def get_bar_colors(df: pd.DataFrame) -> list[str]:
    """Batterie-Balkenfarbe je Steuerbefehl (Modus)."""
    colors = []
    for cmd in df["Steuerbefehl"]:
        text = str(cmd)
        if text.startswith("Zwangsladen"):
            colors.append(COLOR_STEER_FORCE_CHARGE)
        elif text.startswith("Zwangsentladen"):
            colors.append(COLOR_STEER_FORCE_DISCHARGE)
        elif _is_entladesperre_command(text):
            colors.append(COLOR_STEER_ENTLADESPERRE)
        elif text == "Baseline":
            colors.append(COLOR_STEER_BASELINE)
        elif text.startswith("Baseline (Ziel)"):
            colors.append(COLOR_STEER_BASELINE)
        else:
            colors.append(COLOR_STEER_DEFAULT)
    return colors


def _active_consumer_bar_columns(df: pd.DataFrame) -> list[tuple[dict, str]]:
    """Verbraucher-Spalten mit sichtbaren Planwerten (> 0 kWh über den Tag)."""
    active = []
    for consumer in _chart_flex_consumers():
        col = consumer_column_name(consumer)
        if col in df.columns and df[col].fillna(0.0).sum() > 0:
            active.append((consumer, col))
    for appliance in config.get_appliances():
        col = appliance_column_name(appliance)
        if col in df.columns and df[col].fillna(0.0).sum() > 0:
            active.append((appliance_as_chart_consumer(appliance), col))
    return active


def _appliance_horizon_energy_kwh(
    matrix: list[dict] | None,
    chart_window: UiChartWindow | None,
    df: pd.DataFrame,
) -> dict[str, float]:
    """Geplante Energie (kWh) manueller Geräte über SA₀…SA₂."""
    from runtime_store.appliance_schedules import purge_expired

    appliances = config.get_appliances()
    energy = {appliance["id"]: 0.0 for appliance in appliances}
    if not appliances:
        return energy

    def _in_horizon(slot: datetime) -> bool:
        if chart_window is None:
            return True
        normalized = normalize_hour_slot(slot)
        return (
            normalize_hour_slot(chart_window.sa0)
            <= normalized
            <= normalize_hour_slot(chart_window.sa2)
        )

    if matrix:
        schedules = purge_expired()
        if schedules:
            for row in matrix:
                slot = row.get("slot_datetime")
                if not isinstance(slot, datetime) or not _in_horizon(slot):
                    continue
                for appliance_id, kw in appliance_kw_for_slot(slot, schedules).items():
                    energy[appliance_id] = energy.get(appliance_id, 0.0) + kw
        return energy

    for _, row in df.iterrows():
        slot = row.get("slot_datetime")
        if isinstance(slot, datetime) and not _in_horizon(slot):
            continue
        for appliance in appliances:
            col = appliance_column_name(appliance)
            if col in df.columns:
                energy[appliance["id"]] += float(row.get(col, 0.0) or 0.0)
    return energy


def clear_consumer_stack_order_cache() -> None:
    """Test-Hilfe: Stack-Reihenfolge-Cache leeren."""
    _STACK_ORDER_BY_SA0.clear()


def _consumer_horizon_energy_kwh(
    matrix: list[dict] | None,
    chart_window: UiChartWindow | None,
    df: pd.DataFrame,
) -> dict[str, float]:
    """Geplante Flex-Energie (kWh) je Verbraucher über SA₀…SA₂."""
    consumers = _chart_flex_consumers()
    energy = {consumer["id"]: 0.0 for consumer in consumers}
    for appliance in config.get_appliances():
        energy[appliance["id"]] = 0.0
    if matrix and chart_window is not None:
        horizon_start = normalize_hour_slot(chart_window.sa0)
        horizon_end = normalize_hour_slot(chart_window.sa2)
        for row in matrix:
            slot = row.get("slot_datetime")
            if not isinstance(slot, datetime):
                continue
            slot = normalize_hour_slot(slot)
            if not (horizon_start <= slot <= horizon_end):
                continue
            for consumer in consumers:
                col = consumer_column_name(consumer)
                energy[consumer["id"]] += float(row.get(col, 0.0) or 0.0)
        appliance_energy = _appliance_horizon_energy_kwh(matrix, chart_window, df)
        for appliance_id, kwh in appliance_energy.items():
            energy[appliance_id] = energy.get(appliance_id, 0.0) + kwh
        return energy
    if chart_window is not None:
        horizon_start = normalize_hour_slot(chart_window.sa0)
        horizon_end = normalize_hour_slot(chart_window.sa2)
        for _, row in df.iterrows():
            slot = row.get("slot_datetime")
            if isinstance(slot, datetime):
                slot = normalize_hour_slot(slot)
                if not (horizon_start <= slot <= horizon_end):
                    continue
            for consumer in consumers:
                col = consumer_column_name(consumer)
                if col in df.columns:
                    energy[consumer["id"]] += float(row.get(col, 0.0) or 0.0)
        appliance_energy = _appliance_horizon_energy_kwh(None, chart_window, df)
        for appliance_id, kwh in appliance_energy.items():
            energy[appliance_id] = energy.get(appliance_id, 0.0) + kwh
        return energy
    for consumer in consumers:
        col = consumer_column_name(consumer)
        if col in df.columns:
            energy[consumer["id"]] = float(df[col].fillna(0.0).sum())
    appliance_energy = _appliance_horizon_energy_kwh(matrix, chart_window, df)
    for appliance_id, kwh in appliance_energy.items():
        energy[appliance_id] = energy.get(appliance_id, 0.0) + kwh
    return energy


def _stack_order_cache_key(chart_window: UiChartWindow | None) -> str:
    if chart_window is None:
        return "default"
    return chart_window.sa0.isoformat()


def _consumer_stack_order_ids(
    energy_kwh: dict[str, float],
    cache_key: str,
) -> tuple[str, ...]:
    if cache_key in _STACK_ORDER_BY_SA0:
        return _STACK_ORDER_BY_SA0[cache_key]
    stack_entries = [
        *_chart_flex_consumers(),
        *(appliance_as_chart_consumer(appliance) for appliance in config.get_appliances()),
    ]
    ordered = sorted(
        stack_entries,
        key=lambda entry: (-energy_kwh.get(entry["id"], 0.0), entry["id"]),
    )
    order = tuple(entry["id"] for entry in ordered)
    _STACK_ORDER_BY_SA0[cache_key] = order
    return order


def ordered_active_consumers_for_stack(
    df: pd.DataFrame,
    *,
    matrix: list[dict] | None = None,
    chart_window: UiChartWindow | None = None,
) -> list[tuple[dict, str]]:
    """Aktive Flex-Verbraucher für gestapelte Chart-1-Balken (größter Bedarf unten)."""
    active = _active_consumer_bar_columns(df)
    if not active:
        return []
    energy = _consumer_horizon_energy_kwh(matrix, chart_window, df)
    order_ids = _consumer_stack_order_ids(energy, _stack_order_cache_key(chart_window))
    order_index = {consumer_id: index for index, consumer_id in enumerate(order_ids)}
    active.sort(key=lambda pair: order_index.get(pair[0]["id"], len(order_ids)))
    return active

