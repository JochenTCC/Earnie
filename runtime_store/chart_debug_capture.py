"""
chart_debug_capture.py – Chart-Profil-Payload und Kompatibilitaets-API fuer Debug-Dumps.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import config
from runtime_store.debug_dump_archive import (
    DUMP_TYPE_CHART,
    read_zip_bytes,
    resolve_output_dir,
    write_debug_dump_zip,
)
from runtime_store.debug_dump_inputs import collect_dump_context
from runtime_store.live_optimization_debug import _json_safe
from runtime_store import run_state

# Legacy alias; new dumps use schema v2 via debug_dump_archive.
CAPTURE_SCHEMA_VERSION = 1


def _read_json_file(path: str) -> dict[str, Any] | None:
    import os

    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _dataframe_records(df) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        empty = df.empty
    except AttributeError:
        return []
    if empty:
        return []
    return _json_safe(df.to_dict("records"))


def _serialize_deviation_events(
    events: tuple[tuple[Any, ...], ...] | None,
) -> list[list[dict[str, Any]]]:
    if not events:
        return []
    out: list[list[dict[str, Any]]] = []
    for slot_events in events:
        row: list[dict[str, Any]] = []
        for event in slot_events:
            row.append(
                {
                    "rule_id": getattr(event, "rule_id", None),
                    "category": getattr(event, "category", None),
                    "scope": getattr(event, "scope", None),
                    "message": getattr(event, "message", None),
                }
            )
        out.append(row)
    return out


def _serialize_chart_context(chart_context) -> dict[str, Any] | None:
    if chart_context is None:
        return None
    chart = chart_context.chart_window
    zones = chart_context.zones
    return _json_safe(
        {
            "now": chart_context.now,
            "cycle_offset": chart_context.cycle_offset,
            "segment_index": chart_context.segment_index,
            "zone_reference": chart_context.zone_reference,
            "chart_window": {
                "start": chart.start,
                "end": chart.end,
                "sa0": chart.sa0,
                "sa1": chart.sa1,
                "sa2": chart.sa2,
                "segment_index": chart.segment_index,
                "slot_datetimes": chart.slot_datetimes,
            },
            "zones": {
                "history": {
                    "label": zones.history.label,
                    "start": zones.history.start,
                    "end": zones.history.end,
                },
                "live_plan": {
                    "label": zones.live_plan.label,
                    "start": zones.live_plan.start,
                    "end": zones.live_plan.end,
                },
                "forecast": {
                    "label": zones.forecast.label,
                    "start": zones.forecast.start,
                    "end": zones.forecast.end,
                },
            },
        }
    )


def _serialize_sun_markers(sun_markers) -> dict[str, Any] | None:
    if sun_markers is None:
        return None
    return _json_safe(
        {
            "now_x": sun_markers.now_x,
            "sa0_x": sun_markers.sa0_x,
            "sa1_x": sun_markers.sa1_x,
            "sa2_x": sun_markers.sa2_x,
        }
    )


def _read_app_version() -> str:
    try:
        from version import __version__

        return __version__
    except ImportError:
        return "unknown"


def _savings_summary(savings_info: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "baseline_cost_euro",
        "matched_baseline_cost_euro",
        "optimized_cost_euro",
        "savings_euro",
        "savings_matched_euro",
        "baseline_consumption_kwh",
        "matched_baseline_consumption_kwh",
        "optimized_consumption_kwh",
    )
    return {key: savings_info.get(key) for key in keys if key in savings_info}


def build_chart_section(
    bundle,
    *,
    current_soc: float | None,
    live_power: dict[str, Any] | None,
    session_meta: dict[str, Any] | None,
    chart1_plotly_json: str | None,
) -> dict[str, Any]:
    """Chart-profile payload nested under manifest['chart'] (schema v2)."""
    return _json_safe(
        {
            "live_soc_percent": current_soc,
            "live_power": live_power,
            "session_meta": session_meta or {},
            "chart_header_label": bundle.chart_header_label,
            "history_slot_count": bundle.history_slot_count,
            "chart_qualities": list(bundle.chart_qualities or ()),
            "table_gap_notice": bundle.table_gap_notice,
            "matched_cost_euro": bundle.matched_cost,
            "optimized_cost_euro": bundle.optimized_cost,
            "chart_context": _serialize_chart_context(bundle.chart_context),
            "sun_markers": _serialize_sun_markers(bundle.sun_markers),
            "slot_deviation_events": _serialize_deviation_events(
                bundle.slot_deviation_events
            ),
            "display_rows": _dataframe_records(bundle.display_df),
            "table_rows": _dataframe_records(bundle.table_df),
            "baseline_rows": _dataframe_records(bundle.baseline_df),
            "matched_baseline_rows": _dataframe_records(bundle.display_matched),
            "savings_view": _json_safe(dict(bundle.savings_view)),
            "savings_summary": _json_safe(_savings_summary(bundle.savings_info)),
            "chart1_plotly": json.loads(chart1_plotly_json) if chart1_plotly_json else None,
            "run_state": _read_json_file(run_state.RUN_STATE_FILE),
            "battery_params": config.get_battery_params(),
        }
    )


def build_capture_payload(
    bundle,
    *,
    current_soc: float | None,
    live_power: dict[str, Any] | None,
    session_meta: dict[str, Any] | None,
    chart1_plotly_json: str | None,
) -> dict[str, Any]:
    """
    Serialisiert Chart-Zustand.

    Schema-v2-Form mit dump_type/chart; Tests und Replay nutzen normalize_manifest.
    """
    dump_context = collect_dump_context()
    chart = build_chart_section(
        bundle,
        current_soc=current_soc,
        live_power=live_power,
        session_meta=session_meta,
        chart1_plotly_json=chart1_plotly_json,
    )
    return _json_safe(
        {
            "schema_version": 2,
            "dump_type": DUMP_TYPE_CHART,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": _read_app_version(),
            "env_overrides": dump_context["env_overrides"],
            "resolved_paths": dump_context["resolved_paths"],
            "chart": chart,
            # Flat aliases for older test helpers still reading top-level keys.
            **chart,
        }
    )


def write_capture_zip(
    bundle,
    *,
    current_soc: float | None,
    live_power: dict[str, Any] | None = None,
    session_meta: dict[str, Any] | None = None,
    chart1_plotly_json: str | None = None,
    captured_at: datetime | None = None,
) -> str:
    """Write a chart-profile debug dump ZIP. Returns absolute path."""
    chart_payload = build_chart_section(
        bundle,
        current_soc=current_soc,
        live_power=live_power,
        session_meta=session_meta,
        chart1_plotly_json=chart1_plotly_json,
    )
    chart_context = bundle.chart_context
    chart_window = chart_context.chart_window if chart_context else None
    return write_debug_dump_zip(
        DUMP_TYPE_CHART,
        chart_payload=chart_payload,
        chart_window_start=chart_window.start if chart_window else None,
        chart_window_end=chart_window.end if chart_window else None,
        captured_at=captured_at,
    )


__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "build_capture_payload",
    "build_chart_section",
    "read_zip_bytes",
    "resolve_output_dir",
    "write_capture_zip",
]
