"""
chart_debug_capture.py – ZIP-Archiv aller Chart-Plot-Quelldaten (Verdachtsfall-Analyse).
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timedelta
from typing import Any

import config
from runtime_store import optimization_history
from runtime_store.debug_dump_inputs import collect_dump_context, write_inputs_to_zip
from runtime_store.file_metadata import strip_metadata
from runtime_store.live_optimization_debug import _json_safe
from runtime_store.persist_paths import runtime_dir, runtime_path
from runtime_store import run_state

CAPTURE_SCHEMA_VERSION = 1
_HISTORY_PADDING = timedelta(hours=2)


def resolve_output_dir() -> str:
    """Absoluter Pfad für Chart-Debug-ZIPs."""
    configured = config.get_ui_chart_debug_capture_dir()
    if os.path.isabs(configured):
        return configured
    return os.path.join(runtime_dir(), configured)


def _zip_timestamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%d_%H%M%S")


def _read_json_file(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _copy_runtime_file_if_present(archive: zipfile.ZipFile, filename: str) -> None:
    path = runtime_path(filename)
    if os.path.isfile(path):
        archive.write(path, arcname=f"runtime/{filename}")


def _history_window_jsonl(chart_start: datetime, chart_end: datetime) -> str:
    window_start = chart_start - _HISTORY_PADDING
    window_end = chart_end + _HISTORY_PADDING
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    lines: list[str] = []
    for entry in entries:
        payload = strip_metadata(dict(entry))
        lines.append(json.dumps(_json_safe(payload), ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


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


def build_capture_payload(
    bundle,
    *,
    current_soc: float | None,
    live_power: dict[str, Any] | None,
    session_meta: dict[str, Any] | None,
    chart1_plotly_json: str | None,
) -> dict[str, Any]:
    """Serialisiert den aktuellen Chart-Zustand für JSON-Dateien im ZIP."""
    chart_context = bundle.chart_context
    dump_context = collect_dump_context()
    return _json_safe(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": _read_app_version(),
            "live_soc_percent": current_soc,
            "live_power": live_power,
            "session_meta": session_meta or {},
            "chart_header_label": bundle.chart_header_label,
            "history_slot_count": bundle.history_slot_count,
            "chart_qualities": list(bundle.chart_qualities or ()),
            "table_gap_notice": bundle.table_gap_notice,
            "matched_cost_euro": bundle.matched_cost,
            "optimized_cost_euro": bundle.optimized_cost,
            "chart_context": _serialize_chart_context(chart_context),
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
            "env_overrides": dump_context["env_overrides"],
            "resolved_paths": dump_context["resolved_paths"],
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


def write_capture_zip(
    bundle,
    *,
    current_soc: float | None,
    live_power: dict[str, Any] | None = None,
    session_meta: dict[str, Any] | None = None,
    chart1_plotly_json: str | None = None,
    captured_at: datetime | None = None,
) -> str:
    """
    Schreibt ein ZIP mit Plot-Quelldaten. Gibt den absoluten Pfad zurück.
    """
    moment = captured_at or datetime.now()
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    output_dir = resolve_output_dir()
    os.makedirs(output_dir, exist_ok=True)
    zip_name = f"chart_debug_{_zip_timestamp(moment)}.zip"
    zip_path = os.path.join(output_dir, zip_name)

    payload = build_capture_payload(
        bundle,
        current_soc=current_soc,
        live_power=live_power,
        session_meta=session_meta,
        chart1_plotly_json=chart1_plotly_json,
    )

    chart_context = bundle.chart_context
    chart_window = chart_context.chart_window if chart_context else None

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        input_files = write_inputs_to_zip(archive)
        payload["included_input_files"] = input_files
        archive.writestr(
            "manifest.json",
            json.dumps(payload, indent=2, ensure_ascii=False),
        )
        archive.writestr(
            "README.txt",
            (
                "Chart-Debug-Archiv (Earnie)\n"
                "manifest.json – Plot-Tabellen, Kontext, Live-SOC, Plotly Chart 1, Pfadauflosung\n"
                "runtime/optimization_history_window.jsonl – Produktiv-Log um das Chart-Fenster\n"
                "runtime/*.json – Kopien weiterer Laufzeitdateien falls vorhanden\n"
                "inputs/*.json – aktive Konfigurationen fuer spaetere Reproduktion\n"
            ),
        )
        if chart_window is not None:
            archive.writestr(
                "runtime/optimization_history_window.jsonl",
                _history_window_jsonl(chart_window.start, chart_window.end),
            )
        for filename in (
            "optimizer_run_state.json",
            "live_optimization_debug.json",
            "flexible_consumers_state.json",
        ):
            _copy_runtime_file_if_present(archive, filename)

    return zip_path


def read_zip_bytes(zip_path: str) -> bytes:
    with open(zip_path, "rb") as handle:
        return handle.read()
