"""Unified debug-dump ZIP (chart UI + prod/optimizer profiles), schema v2."""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config
from runtime_store import optimization_history
from runtime_store.debug_dump_inputs import collect_dump_context, write_inputs_to_zip
from runtime_store.file_metadata import strip_metadata
from runtime_store.live_optimization_debug import _json_safe
from runtime_store.persist_paths import runtime_dir, runtime_path

DUMP_SCHEMA_VERSION = 2
DUMP_TYPE_CHART = "chart"
DUMP_TYPE_PROD = "prod"
DUMP_TYPES = (DUMP_TYPE_CHART, DUMP_TYPE_PROD)

_HISTORY_PADDING = timedelta(hours=2)

_OPTIONAL_RUNTIME_BOTH = (
    "optimizer_run_state.json",
    "live_optimization_debug.json",
    "flexible_consumers_state.json",
)
_OPTIONAL_RUNTIME_PROD = ("pv_counter_state.json",)

# Arcnames relative to ZIP root.
PROFILE_REQUIRED: dict[str, tuple[str, ...]] = {
    DUMP_TYPE_CHART: ("runtime/optimization_history_window.jsonl",),
    DUMP_TYPE_PROD: ("runtime/optimization_history.jsonl",),
}
PROFILE_OPTIONAL: dict[str, tuple[str, ...]] = {
    DUMP_TYPE_CHART: tuple(f"runtime/{name}" for name in _OPTIONAL_RUNTIME_BOTH),
    DUMP_TYPE_PROD: tuple(
        f"runtime/{name}"
        for name in _OPTIONAL_RUNTIME_BOTH + _OPTIONAL_RUNTIME_PROD
    ),
}


def resolve_output_dir() -> str:
    """Absolute path for debug-dump ZIPs (config key chart_debug_capture_dir)."""
    configured = config.get_ui_chart_debug_capture_dir()
    if os.path.isabs(configured):
        return configured
    return os.path.join(runtime_dir(), configured)


def _zip_timestamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%d_%H%M%S")


def _read_app_version() -> str:
    try:
        from version import __version__

        return __version__
    except ImportError:
        return "unknown"


def _copy_runtime_file_if_present(
    archive: zipfile.ZipFile, filename: str
) -> str | None:
    path = runtime_path(filename)
    if not os.path.isfile(path):
        return None
    arcname = f"runtime/{filename}"
    archive.write(path, arcname=arcname)
    return arcname


def _history_window_jsonl(chart_start: datetime, chart_end: datetime) -> str:
    window_start = chart_start - _HISTORY_PADDING
    window_end = chart_end + _HISTORY_PADDING
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    lines: list[str] = []
    for entry in entries:
        payload = strip_metadata(dict(entry))
        lines.append(json.dumps(_json_safe(payload), ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def _readme_text(dump_type: str) -> str:
    required = ", ".join(PROFILE_REQUIRED[dump_type])
    optional = ", ".join(PROFILE_OPTIONAL[dump_type])
    return (
        f"Earnie Debug-Dump (dump_type={dump_type}, schema_version={DUMP_SCHEMA_VERSION})\n"
        "manifest.json – Metadaten, Pfadaufloesung, profilspezifische Felder\n"
        "inputs/* – aktive Konfigurationen fuer spaetere Reproduktion\n"
        f"Required runtime: {required}\n"
        f"Optional runtime: {optional}\n"
        "Replay: python -m scripts.replay_debug_dump <zip-or-dir>\n"
    )


def _base_manifest(
    *,
    dump_type: str,
    captured_at: datetime,
    dump_context: dict[str, object],
) -> dict[str, Any]:
    return {
        "schema_version": DUMP_SCHEMA_VERSION,
        "dump_type": dump_type,
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "app_version": _read_app_version(),
        "env_overrides": dump_context["env_overrides"],
        "resolved_paths": dump_context["resolved_paths"],
        "files": {
            "required_present": [],
            "optional_present": [],
        },
        "included_input_files": [],
    }


def write_debug_dump_zip(
    dump_type: str,
    *,
    chart_payload: dict[str, Any] | None = None,
    chart_window_start: datetime | None = None,
    chart_window_end: datetime | None = None,
    title: str = "",
    symptom: str = "",
    case_id: str = "",
    captured_at: datetime | None = None,
) -> str:
    """
    Write a unified debug-dump ZIP. Returns absolute path.

    Chart dumps require ``chart_payload`` and preferably a chart window for
    the history slice. Prod dumps require ``runtime/optimization_history.jsonl``.
    """
    if dump_type not in DUMP_TYPES:
        raise ValueError(f"Unknown dump_type: {dump_type!r}")
    if dump_type == DUMP_TYPE_CHART and chart_payload is None:
        raise ValueError("chart dump requires chart_payload")

    moment = captured_at or datetime.now()
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)

    output_dir = resolve_output_dir()
    os.makedirs(output_dir, exist_ok=True)
    zip_name = f"debug_dump_{dump_type}_{_zip_timestamp(moment)}.zip"
    zip_path = os.path.join(output_dir, zip_name)

    dump_context = collect_dump_context()
    manifest = _base_manifest(
        dump_type=dump_type,
        captured_at=moment,
        dump_context=dump_context,
    )
    if dump_type == DUMP_TYPE_CHART:
        manifest["chart"] = chart_payload
    else:
        manifest["prod"] = {
            "title": title or "",
            "symptom": symptom or "",
            "case_id": case_id or "",
        }

    required_present: list[str] = []
    optional_present: list[str] = []

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        input_files = write_inputs_to_zip(archive)
        manifest["included_input_files"] = input_files

        if dump_type == DUMP_TYPE_CHART:
            if chart_window_start is not None and chart_window_end is not None:
                archive.writestr(
                    "runtime/optimization_history_window.jsonl",
                    _history_window_jsonl(chart_window_start, chart_window_end),
                )
                required_present.append("runtime/optimization_history_window.jsonl")
            else:
                archive.writestr("runtime/optimization_history_window.jsonl", "")
                required_present.append("runtime/optimization_history_window.jsonl")
            for filename in _OPTIONAL_RUNTIME_BOTH:
                written = _copy_runtime_file_if_present(archive, filename)
                if written:
                    optional_present.append(written)
        else:
            history_src = runtime_path(optimization_history.HISTORY_FILENAME)
            if not os.path.isfile(history_src):
                raise FileNotFoundError(
                    f"{optimization_history.HISTORY_FILENAME} fehlt – "
                    "Prod-Dump abgebrochen"
                )
            archive.write(history_src, arcname="runtime/optimization_history.jsonl")
            required_present.append("runtime/optimization_history.jsonl")
            for filename in _OPTIONAL_RUNTIME_BOTH + _OPTIONAL_RUNTIME_PROD:
                written = _copy_runtime_file_if_present(archive, filename)
                if written:
                    optional_present.append(written)

        manifest["files"] = {
            "required_present": required_present,
            "optional_present": optional_present,
        }
        archive.writestr(
            "manifest.json",
            json.dumps(_json_safe(manifest), indent=2, ensure_ascii=False),
        )
        archive.writestr("README.txt", _readme_text(dump_type))

    return zip_path


def read_zip_bytes(zip_path: str) -> bytes:
    with open(zip_path, "rb") as handle:
        return handle.read()


def normalize_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize schema v1 chart manifests and v2 dumps to a common shape.

    Returns a dict with at least schema_version, dump_type, and chart/prod.
    """
    if not isinstance(raw, dict):
        raise ValueError("manifest.json is not a JSON object")
    version = int(raw.get("schema_version") or 0)
    if version >= DUMP_SCHEMA_VERSION and raw.get("dump_type") in DUMP_TYPES:
        return raw
    # Schema v1 chart dump: flat payload, no dump_type.
    if version == 1 or (
        version == 0 and ("display_rows" in raw or "chart_context" in raw)
    ):
        chart_keys = (
            "live_soc_percent",
            "live_power",
            "session_meta",
            "chart_header_label",
            "history_slot_count",
            "chart_qualities",
            "table_gap_notice",
            "matched_cost_euro",
            "optimized_cost_euro",
            "chart_context",
            "sun_markers",
            "slot_deviation_events",
            "display_rows",
            "table_rows",
            "baseline_rows",
            "matched_baseline_rows",
            "savings_view",
            "savings_summary",
            "chart1_plotly",
            "run_state",
            "battery_params",
        )
        chart = {key: raw[key] for key in chart_keys if key in raw}
        return {
            "schema_version": version or 1,
            "dump_type": DUMP_TYPE_CHART,
            "captured_at": raw.get("captured_at"),
            "app_version": raw.get("app_version"),
            "env_overrides": raw.get("env_overrides") or {},
            "resolved_paths": raw.get("resolved_paths") or {},
            "included_input_files": raw.get("included_input_files") or [],
            "files": raw.get("files")
            or {
                "required_present": ["runtime/optimization_history_window.jsonl"],
                "optional_present": [],
            },
            "chart": chart,
            "_normalized_from_v1": True,
        }
    dump_type = raw.get("dump_type")
    if dump_type in DUMP_TYPES:
        return raw
    raise ValueError(
        f"Unsupported dump manifest (schema_version={version!r}, "
        f"dump_type={dump_type!r})"
    )


def load_manifest_from_dir(root: str | Path) -> dict[str, Any]:
    path = Path(root) / "manifest.json"
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    return normalize_manifest(raw)


def extract_dump_to_dir(source: str | Path, target: str | Path | None = None) -> Path:
    """Extract a dump ZIP to ``target`` (or a temp dir). Returns the root path."""
    source_path = Path(source)
    if source_path.is_dir():
        return source_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Dump not found: {source_path}")
    out = Path(target) if target else Path(tempfile.mkdtemp(prefix="debug_dump_"))
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path, "r") as archive:
        archive.extractall(out)
    return out.resolve()


def validate_dump_layout(
    root: str | Path,
    dump_type: str | None = None,
) -> dict[str, Any]:
    """
    Validate required files for a dump directory.

    Returns the normalized manifest. Raises ValueError on missing required files.
    """
    root_path = Path(root)
    manifest = load_manifest_from_dir(root_path)
    resolved_type = dump_type or manifest.get("dump_type")
    if resolved_type not in DUMP_TYPES:
        raise ValueError(f"Unknown dump_type: {resolved_type!r}")
    missing: list[str] = []
    for arcname in PROFILE_REQUIRED[resolved_type]:
        if not (root_path / arcname).is_file():
            missing.append(arcname)
    if missing:
        raise ValueError(
            f"Dump incomplete for type={resolved_type}: missing {', '.join(missing)}"
        )
    return manifest
