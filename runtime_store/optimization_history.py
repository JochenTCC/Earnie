"""
optimization_history.py – Persistierte Produktiv-Optimierungen (main.py) für die App.

Läufe: runtime/optimization_history.jsonl (append-only, JSONL only).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

import config
from data.planning_window import align_to_planning_timezone
from .file_metadata import OPTIMIZATION_HISTORY_SCHEMA, stamp_payload, strip_metadata
from .persist_paths import runtime_dir as persist_runtime_dir

logger = logging.getLogger(__name__)

from runtime_store.env_vars import read_runtime_path

HISTORY_FILENAME = "optimization_history.jsonl"
# Module attrs are patchable in tests; init via persist_paths so EARNIE_ENV_PATH
# alone resolves to {ENV_PATH}/runtime (not cwd-relative "runtime/").
RUNTIME_DIR = persist_runtime_dir()
HISTORY_FILE = os.path.join(RUNTIME_DIR, HISTORY_FILENAME)

_JSONL_HISTORY_CACHE: tuple[tuple[int, int], list[dict[str, Any]]] | None = None
_JSONL_HISTORY_CACHE_PATH: str | None = None

MODE_LABELS = {
    0: "Automatik",
    1: "Zwangs-Laden",
    2: "Halten",
    3: "Zwangs-Entladen",
}

_HISTORY_COLUMNS = [
    "completed_at",
    "run_trigger_label",
    "soc_percent",
    "mode_label",
    "target_power_kw",
    "target_soc_percent",
    "market_price_cent",
    "forecast_pv_kw",
    "forecast_consumption_kw",
    "battery_plan_kw",
    "flex_summary",
    "source",
]


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def resolved_runtime_dir() -> str:
    """Active runtime dir (ENV_PATH / RUNTIME_PATH); honors test monkeypatch of RUNTIME_DIR."""
    return RUNTIME_DIR


def history_file_path() -> str:
    """Active history JSONL path; honors test monkeypatch of HISTORY_FILE."""
    return HISTORY_FILE


def append_production_run(payload: dict[str, Any]) -> None:
    """Hängt einen main.py-Durchlauf an die JSONL-Historie an."""
    path = history_file_path()
    entry = stamp_payload(dict(payload), schema_version=OPTIMIZATION_HISTORY_SCHEMA)
    _ensure_parent_dir(path)
    line = json.dumps(entry, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.write("\n")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _entry_completed_at(clean: dict[str, Any]) -> datetime | None:
    """Zeitstempel eines JSONL-Eintrags (completed_at, sonst written_at)."""
    completed = _parse_timestamp(clean.get("completed_at"))
    if completed is not None:
        return completed
    return _parse_timestamp(clean.get("written_at"))


def _flex_summary(consumer_powers: dict | None) -> str:
    if not consumer_powers:
        return ""
    parts = []
    for consumer in config.get_flexible_consumers():
        cid = consumer["id"]
        kw = float((consumer_powers or {}).get(cid, 0.0) or 0.0)
        if kw > 0:
            parts.append(f"{consumer['name']} {kw:.2f} kW")
    return " · ".join(parts)


def _format_run_trigger_label(run_trigger: str | None) -> str:
    if not run_trigger or run_trigger == "quarter_hour":
        return "Viertelstunde"
    if run_trigger == "request_optimize":
        return "Request Optimize"
    if run_trigger.startswith("event:"):
        return run_trigger.split(":", 1)[1]
    if run_trigger.startswith("ev_plugged_in:"):
        return f"Anstecken ({run_trigger.split(':', 1)[1]})"
    if run_trigger.startswith("ev_unplugged:"):
        return f"Abstecken ({run_trigger.split(':', 1)[1]})"
    return str(run_trigger)


def _row_from_json_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    completed = _entry_completed_at(entry)
    if completed is None:
        return None
    clean = strip_metadata(entry)
    mode = int(clean.get("mode", 0))
    raw = dict(clean)
    raw["completed_at"] = completed.isoformat(timespec="seconds")
    return {
        "completed_at": completed,
        "run_trigger_label": _format_run_trigger_label(clean.get("run_trigger")),
        "soc_percent": float(clean.get("soc_percent", 0.0) or 0.0),
        "mode_label": MODE_LABELS.get(mode, str(mode)),
        "target_power_kw": float(clean.get("target_power_kw", 0.0) or 0.0),
        "target_soc_percent": float(clean.get("target_soc_percent", 0.0) or 0.0),
        "market_price_cent": float(clean.get("market_price_cent", 0.0) or 0.0),
        "forecast_pv_kw": float(clean.get("forecast_pv_kw", 0.0) or 0.0),
        "forecast_consumption_kw": float(clean.get("forecast_consumption_kw", 0.0) or 0.0),
        "battery_plan_kw": float(clean.get("battery_plan_kw", 0.0) or 0.0),
        "flex_summary": _flex_summary(clean.get("consumer_powers_kw")),
        "source": str(clean.get("source", "main.py")),
        "_raw": raw,
    }


def _load_jsonl_history() -> list[dict[str, Any]]:
    global _JSONL_HISTORY_CACHE, _JSONL_HISTORY_CACHE_PATH
    path = history_file_path()
    if not os.path.isfile(path):
        return []
    stat = os.stat(path)
    cache_key = (int(stat.st_mtime_ns), int(stat.st_size))
    if (
        _JSONL_HISTORY_CACHE is not None
        and _JSONL_HISTORY_CACHE_PATH == path
        and _JSONL_HISTORY_CACHE[0] == cache_key
    ):
        return list(_JSONL_HISTORY_CACHE[1])
    rows: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    entry = json.loads(text)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "optimization_history: Zeile %s in %s ungültig: %s",
                        line_no,
                        path,
                        exc,
                    )
                    continue
                if not isinstance(entry, dict):
                    continue
                row = _row_from_json_entry(entry)
                if row is not None:
                    rows.append(row)
    except OSError as exc:
        logger.warning("optimization_history: %s konnte nicht gelesen werden: %s", path, exc)
    _JSONL_HISTORY_CACHE = (cache_key, rows)
    _JSONL_HISTORY_CACHE_PATH = path
    return rows


def _sorted_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort JSONL rows by completed_at ascending."""
    return sorted(rows, key=lambda item: item["completed_at"])


def load_optimization_history(days_back: int | None = 7) -> pd.DataFrame:
    """Lädt die Produktiv-Historie als DataFrame (neueste zuerst)."""
    rows = _sorted_history_rows(_load_jsonl_history())
    if days_back is not None:
        cutoff = datetime.now() - timedelta(days=int(days_back))
        rows = [row for row in rows if row["completed_at"] >= cutoff]
    if not rows:
        return pd.DataFrame(columns=_HISTORY_COLUMNS)
    display_rows = [{key: row.get(key) for key in _HISTORY_COLUMNS} for row in reversed(rows)]
    return pd.DataFrame(display_rows)


def load_history_entry_at(completed_at: datetime) -> dict[str, Any] | None:
    """Rohdaten eines JSONL-Eintrags zu einem Zeitpunkt (für Detailansicht)."""
    for row in _load_jsonl_history():
        delta = abs((row["completed_at"] - completed_at).total_seconds())
        if delta < 60:
            return row.get("_raw")
    return None


def _replay_entry_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("_raw")
    if isinstance(raw, dict):
        return strip_metadata(raw)
    return None


def _align_replay_timestamp(moment: datetime) -> datetime:
    """Naive JSONL-Zeitstempel in die Planungszeitzone bringen."""
    return align_to_planning_timezone(moment, config.get_planning_timezone())


def _completed_in_window(completed: datetime, start: datetime, end: datetime) -> bool:
    completed_aligned = _align_replay_timestamp(completed)
    start_aligned = _align_replay_timestamp(start)
    end_aligned = _align_replay_timestamp(end)
    return start_aligned <= completed_aligned < end_aligned


def load_replay_entries_between(
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    """Produktiv-Einträge mit completed_at in [window_start, window_end) (JSONL only)."""
    merged = _sorted_history_rows(_load_jsonl_history())
    entries: list[dict[str, Any]] = []
    for row in merged:
        completed = row.get("completed_at")
        if not isinstance(completed, datetime):
            continue
        if not _completed_in_window(completed, window_start, window_end):
            continue
        entry = _replay_entry_from_row(row)
        if entry is not None:
            entries.append(entry)
    return entries


def earliest_replay_completed_at() -> datetime | None:
    """Frühester bekanntes completed_at aus JSONL."""
    merged = _sorted_history_rows(_load_jsonl_history())
    if not merged:
        return None
    return merged[0]["completed_at"]


def latest_logged_soc_percent() -> float | None:
    """Letzter geloggter ESS-SoC aus optimization_history.jsonl."""
    merged = _sorted_history_rows(_load_jsonl_history())
    if not merged:
        return None
    raw = merged[-1].get("_raw") or merged[-1]
    if not isinstance(raw, dict):
        return None
    soc = raw.get("soc_percent")
    if soc is None:
        return None
    return float(soc)


@dataclass(frozen=True)
class ProductionLogSourceInfo:
    """Metadaten zur aktuell eingebundenen Produktiv-Log-Datei."""

    runtime_dir: str
    env_runtime_dir: str | None
    history_file: str
    history_exists: bool
    history_size_bytes: int | None
    history_modified_at: datetime | None


def describe_production_log_source() -> ProductionLogSourceInfo:
    """
    Beschreibt, welche Datei die UI für den Produktiv-Log liest.

    Nutzt die gleichen Modul-Pfade wie die Loader (``HISTORY_FILE`` / ``RUNTIME_DIR``),
    die über ``persist_paths.runtime_dir()`` initialisiert werden (``EARNIE_ENV_PATH``
    oder ``EARNIE_RUNTIME_PATH``).
    """
    runtime_dir = os.path.abspath(resolved_runtime_dir())
    history_file = os.path.abspath(history_file_path())
    history_exists = os.path.isfile(history_file)
    history_size: int | None = None
    history_mtime: datetime | None = None
    if history_exists:
        stat = os.stat(history_file)
        history_size = stat.st_size
        history_mtime = datetime.fromtimestamp(stat.st_mtime)
    return ProductionLogSourceInfo(
        runtime_dir=runtime_dir,
        env_runtime_dir=read_runtime_path() or None,
        history_file=history_file,
        history_exists=history_exists,
        history_size_bytes=history_size,
        history_modified_at=history_mtime,
    )
