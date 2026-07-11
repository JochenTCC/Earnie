"""Diagnose SwimSpa Soll: Chart vs Tabelle (nur NAS-Produktiv-Log)."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from optimizer.targets import consumer_column_name
from runtime_store import optimization_history
from runtime_store.history_timeline import (
    SLOT_PRESENT,
    _index_entries_by_slot,
    build_chart_history,
)
from ui.chart_context import build_live_chart_context, build_chart_display_context
from ui.charts import (
    _extrapolation_bounds,
    _mask_missing_log_slots,
    add_power_traces,
    get_bar_colors,
    ChartSlotAxis,
)


from runtime_store.env_vars import read_env


def _require_nas_runtime() -> str:
    runtime = read_env("RUNTIME_DIR")
    if not runtime or "DS-KO-DO-2" not in runtime.replace("/", "\\"):
        raise SystemExit(
            "EARNIE_RUNTIME_DIR muss auf NAS zeigen "
            "(z. B. \\\\DS-KO-DO-2\\docker\\earnie\\runtime)."
        )
    if not os.path.isfile(optimization_history.HISTORY_FILE):
        raise SystemExit(f"NAS-Log fehlt: {optimization_history.HISTORY_FILE}")
    return runtime


def _load_nas_sim_rows(now: datetime) -> list[dict]:
    """MILP-Zeilen aus NAS-Debug, falls vorhanden."""
    debug_path = Path(optimization_history.RUNTIME_DIR) / "live_optimization_debug.json"
    if not debug_path.is_file():
        return []
    import json

    rows = json.loads(debug_path.read_text(encoding="utf-8")).get("simulation_rows") or []
    for row in rows:
        slot = row.get("slot_datetime")
        if isinstance(slot, str):
            row["slot_datetime"] = datetime.fromisoformat(slot)
    return rows


def _swimspa_chart_bars(
    df: pd.DataFrame,
    slot_qualities: tuple[str, ...],
    history_slot_count: int,
    col: str,
) -> dict[str, float | None]:
    """Plotly SwimSpa-Balken: Uhrzeit -> y-Wert (wie Chart-Hover)."""
    plot_df = _mask_missing_log_slots(df, slot_qualities)
    # tz-aware slot_datetime: Plotly-Pfad braucht UTC für pandas
    plot_df = plot_df.copy()
    if "slot_datetime" in plot_df.columns:
        plot_df["slot_datetime"] = pd.to_datetime(plot_df["slot_datetime"], utc=True)
    axis = ChartSlotAxis.from_dataframe(plot_df)
    fig = go.Figure()
    extrap_start, extrap_end = _extrapolation_bounds(plot_df)
    add_power_traces(
        fig,
        plot_df,
        get_bar_colors(plot_df),
        axis,
        extrap_start,
        extrap_end,
    )
    history_labels = {
        row["Uhrzeit"] for row in df.to_dict("records")[:history_slot_count]
    }
    bars: dict[str, float | None] = {}
    for trace in fig.data:
        if trace.name != "SwimSpa" or trace.type != "bar":
            continue
        for y_val, custom in zip(trace.y, trace.customdata or []):
            if not custom:
                continue
            label = str(custom[0])
            if label not in history_labels:
                continue
            y = None if y_val is None or (isinstance(y_val, float) and y_val != y_val) else float(y_val)
            bars[label] = y
    return bars


def main() -> None:
    nas = _require_nas_runtime()
    tz = ZoneInfo(config.get_planning_timezone())
    now = datetime.now(tz)

    print("=== SwimSpa Soll-Diagnose (nur NAS) ===")
    print(f"NAS: {nas}")
    print(f"Log: {optimization_history.HISTORY_FILE}")
    print(f"now (simuliert): {now.isoformat()}")

    swimspa = next(
        c for c in config.get_flexible_consumers(optimizer_only=True) if c["id"] == "swimspa"
    )
    col = consumer_column_name(swimspa)

    ctx = build_live_chart_context(0, 0, now=now)
    sim_rows = _load_nas_sim_rows(now)
    print(f"MILP sim_rows: {len(sim_rows)} (aus NAS live_optimization_debug.json)")

    disp = build_chart_display_context(ctx, sim_rows or None)
    df = pd.DataFrame(disp.rows)
    chart_bars = _swimspa_chart_bars(
        df,
        disp.slot_qualities,
        disp.history_slot_count,
        col,
    )

    print(f"history.end: {ctx.zones.history.end}")
    print()
    print(f"{'idx':>4} {'Uhrzeit':<14} {'quality':<10} {'Tabelle':<10} {'Chart':<10} {'Match':<6}")
    mismatches = 0
    for i, row in enumerate(disp.rows):
        if i >= disp.history_slot_count:
            break
        label = row["Uhrzeit"]
        if "04.07." not in label:
            continue
        hour = label.split()[-1] if " " in label else label
        if not (hour.startswith("09:") or hour.startswith("10:") or hour.startswith("11:") or hour.startswith("12:")):
            continue
        q = disp.slot_qualities[i]
        table_val = row.get(col)
        chart_val = chart_bars.get(label)
        table_s = "null" if table_val is None else f"{float(table_val):.2f}"
        if chart_val is None:
            chart_s = "—"
        else:
            chart_s = f"{chart_val:.2f}"
        match = "OK" if table_s == chart_s or (table_s == "null" and chart_s == "—") else "DIFF"
        if match == "DIFF":
            mismatches += 1
        print(f"{i:4d} {label:<14} {q:<10} {table_s:<10} {chart_s:<10} {match}")

    print()
    print(f"Abweichungen Tabelle vs Chart (09-12): {mismatches}")

    print()
    print("=== NAS Log Soll (consumer_powers_kw.swimspa) 09:00-12:00 ===")
    entries = optimization_history.load_replay_entries_between(
        ctx.chart_window.start, ctx.zones.history.end
    )
    by_slot = _index_entries_by_slot(entries)
    window_start = datetime(2026, 7, 4, 9, 0, tzinfo=tz)
    window_end = datetime(2026, 7, 4, 12, 0, tzinfo=tz)
    for slot in sorted(by_slot.keys()):
        if slot < window_start or slot >= window_end:
            continue
        entry = by_slot[slot]
        soll = (entry.get("consumer_powers_kw") or {}).get("swimspa")
        ist = ((entry.get("consumption_snapshot") or {}).get("flex_kw") or {}).get("swimspa")
        print(f"  {slot.strftime('%H:%M')}  soll={soll}  ist={ist}  written={str(entry.get('written_at',''))[:19]}")

    # Check for MILP bleed into history zone
    print()
    print("=== Slots mit quality=milp aber Uhrzeit in 09-12? ===")
    for i, row in enumerate(disp.rows):
        label = row["Uhrzeit"]
        if "04.07." not in label:
            continue
        hour = label.split()[-1] if " " in label else label
        if not hour.startswith(("09:", "10:", "11:")):
            continue
        q = disp.slot_qualities[i]
        if q != SLOT_PRESENT and i < disp.history_slot_count:
            print(f"  {i} {label} q={q} table={row.get(col)}")
        if q == "milp" and hour < "12:00":
            print(f"  MILP in history window: {i} {label} swimspa={row.get(col)}")


    print()
    print("=== BUG-Szenario: Tabelle nur MILP-align (ohne Log), Chart display_ctx ===")
    from ui.chart_context import align_rows_to_chart_slots

    table_milp_only = pd.DataFrame(
        align_rows_to_chart_slots(sim_rows, ctx.chart_window)
    )
    col_name = col
    mism_milp = 0
    for i in range(disp.history_slot_count):
        t_row = table_milp_only.iloc[i] if i < len(table_milp_only) else None
        c_row = disp.rows[i]
        label = c_row["Uhrzeit"]
        if "04.07." not in label:
            continue
        hour = label.split()[-1]
        if not hour.startswith(("09:", "10:", "11:", "12:")):
            continue
        tv = t_row.get(col_name) if t_row is not None else None
        cv = c_row.get(col_name)
        if tv != cv:
            mism_milp += 1
            print(f"  {label}  tabelle={tv}  chart={cv}")
    if mism_milp == 0:
        print("  (keine Abweichung in diesem Szenario)")
    else:
        print(f"  Abweichungen: {mism_milp}")


if __name__ == "__main__":
    main()
