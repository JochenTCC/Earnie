"""
optimization_history.py – Persistierte Produktiv-Optimierungen (main.py) für die App.

Neue Läufe: runtime/optimization_history.jsonl (append-only).
Legacy: system_history_log.csv (nur Lesen).
"""
from __future__ import annotations

import json
import logging
import os
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

import config
from data.planning_window import align_to_planning_timezone
from .file_metadata import OPTIMIZATION_HISTORY_SCHEMA, stamp_payload, strip_metadata
from .persist_paths import legacy_history_csv_file

logger = logging.getLogger(__name__)

RUNTIME_DIR = os.environ.get("ENERGY_OPTIMIZER_RUNTIME_DIR", "runtime")
HISTORY_FILENAME = "optimization_history.jsonl"
HISTORY_FILE = os.path.join(RUNTIME_DIR, HISTORY_FILENAME)
LEGACY_CSV_FILE = legacy_history_csv_file()

_JSONL_HISTORY_CACHE: tuple[tuple[int, int], list[dict[str, Any]]] | None = None

_LEGACY_CSV_COLUMNS = (
    "Timestamp",
    "SoC_%",
    "Awattar_Price",
    "PV_Forecast_kW",
    "Consumption_Forecast_kW",
    "Ernie_Mode",
    "Target_Power_kW",
    "Target_SoC_%",
)

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


def history_file_path() -> str:
    return HISTORY_FILE


def append_production_run(payload: dict[str, Any]) -> None:
    """Hängt einen main.py-Durchlauf an die JSONL-Historie an."""
    entry = stamp_payload(dict(payload), schema_version=OPTIMIZATION_HISTORY_SCHEMA)
    _ensure_parent_dir(HISTORY_FILE)
    line = json.dumps(entry, ensure_ascii=False)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
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


def _float_or_zero(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    return float(text)


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
    global _JSONL_HISTORY_CACHE
    if not os.path.isfile(HISTORY_FILE):
        return []
    stat = os.stat(HISTORY_FILE)
    cache_key = (int(stat.st_mtime_ns), int(stat.st_size))
    if _JSONL_HISTORY_CACHE is not None and _JSONL_HISTORY_CACHE[0] == cache_key:
        return list(_JSONL_HISTORY_CACHE[1])
    rows: list[dict[str, Any]] = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
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
                        HISTORY_FILE,
                        exc,
                    )
                    continue
                if not isinstance(entry, dict):
                    continue
                row = _row_from_json_entry(entry)
                if row is not None:
                    rows.append(row)
    except OSError as exc:
        logger.warning("optimization_history: %s konnte nicht gelesen werden: %s", HISTORY_FILE, exc)
    _JSONL_HISTORY_CACHE = (cache_key, rows)
    return rows


def _normalize_legacy_csv_fields(fields: list[str]) -> list[str] | None:
    """
    Alte system_history_log.csv: 7 Spalten ohne Target_SoC_%.
    Neuere Zeilen (main.py): 8 Spalten.
    """
    if len(fields) < 7:
        return None
    if len(fields) == 7:
        return fields + [""]
    if len(fields) > 8:
        logger.warning(
            "optimization_history: Legacy-Zeile mit %s Feldern gekürzt (erwartet 7–8).",
            len(fields),
        )
    return fields[:8]


def _read_legacy_csv(path: str) -> pd.DataFrame:
    """Liest Legacy-CSV robust, auch bei gemischten 7- und 8-Spalten-Zeilen."""
    parsed_rows: list[list[str]] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return pd.DataFrame(columns=_LEGACY_CSV_COLUMNS)

        for line_no, fields in enumerate(reader, start=2):
            if not fields or all(not cell.strip() for cell in fields):
                continue
            normalized = _normalize_legacy_csv_fields(fields)
            if normalized is None:
                logger.warning(
                    "optimization_history: Zeile %s in %s übersprungen (%s Felder).",
                    line_no,
                    path,
                    len(fields),
                )
                continue
            parsed_rows.append(normalized)

    if not parsed_rows:
        return pd.DataFrame(columns=_LEGACY_CSV_COLUMNS)
    return pd.DataFrame(parsed_rows, columns=_LEGACY_CSV_COLUMNS)


def _load_legacy_csv_history() -> list[dict[str, Any]]:
    if not os.path.isfile(LEGACY_CSV_FILE):
        return []
    try:
        df = _read_legacy_csv(LEGACY_CSV_FILE)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("optimization_history: %s konnte nicht gelesen werden: %s", LEGACY_CSV_FILE, exc)
        return []

    rows: list[dict[str, Any]] = []
    for _, record in df.iterrows():
        completed = _parse_timestamp(record.get("Timestamp"))
        if completed is None:
            continue
        mode = int(record.get("Ernie_Mode", 0))
        rows.append({
            "completed_at": completed,
            "run_trigger_label": "Viertelstunde",
            "soc_percent": float(record.get("SoC_%", 0.0) or 0.0),
            "mode_label": MODE_LABELS.get(mode, str(mode)),
            "target_power_kw": float(record.get("Target_Power_kW", 0.0) or 0.0),
            "target_soc_percent": _float_or_zero(record.get("Target_SoC_%")),
            "market_price_cent": float(record.get("Awattar_Price", 0.0) or 0.0),
            "forecast_pv_kw": float(record.get("PV_Forecast_kW", 0.0) or 0.0),
            "forecast_consumption_kw": float(record.get("Consumption_Forecast_kW", 0.0) or 0.0),
            "battery_plan_kw": None,
            "flex_summary": "",
            "source": "system_history_log.csv",
            "_raw": None,
        })
    return rows


def _merge_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """JSONL bevorzugen; CSV nur für Zeitpunkte ohne JSONL-Eintrag."""
    by_time: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        if row["source"] == "system_history_log.csv":
            by_time.setdefault(row["completed_at"], row)
    for row in rows:
        if row["source"] != "system_history_log.csv":
            by_time[row["completed_at"]] = row
    return sorted(by_time.values(), key=lambda item: item["completed_at"])


def load_optimization_history(days_back: int | None = 7) -> pd.DataFrame:
    """Lädt die Produktiv-Historie als DataFrame (neueste zuerst)."""
    rows = _merge_history_rows(_load_jsonl_history() + _load_legacy_csv_history())
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


def _legacy_record_to_replay_entry(
    record: pd.Series,
    completed: datetime,
) -> dict[str, Any]:
    mode = int(record.get("Ernie_Mode", 0))
    return {
        "completed_at": completed.isoformat(timespec="seconds"),
        "source": "system_history_log.csv",
        "success": True,
        "soc_percent": float(record.get("SoC_%", 0.0) or 0.0),
        "mode": mode,
        "target_power_kw": float(record.get("Target_Power_kW", 0.0) or 0.0),
        "target_soc_percent": _float_or_zero(record.get("Target_SoC_%")),
        "market_price_cent": float(record.get("Awattar_Price", 0.0) or 0.0),
        "forecast_pv_kw": float(record.get("PV_Forecast_kW", 0.0) or 0.0),
        "forecast_consumption_kw": float(record.get("Consumption_Forecast_kW", 0.0) or 0.0),
        "battery_plan_kw": None,
        "consumer_powers_kw": {},
        "consumer_pv_follow": {},
    }


def _replay_entry_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("_raw")
    if isinstance(raw, dict):
        return strip_metadata(raw)
    if row.get("source") == "system_history_log.csv":
        completed = row.get("completed_at")
        if isinstance(completed, datetime):
            return _legacy_record_to_replay_entry(
                pd.Series({
                    "Ernie_Mode": _mode_from_label(row.get("mode_label", "")),
                    "SoC_%": row.get("soc_percent"),
                    "Target_Power_kW": row.get("target_power_kw"),
                    "Target_SoC_%": row.get("target_soc_percent"),
                    "Awattar_Price": row.get("market_price_cent"),
                    "PV_Forecast_kW": row.get("forecast_pv_kw"),
                    "Consumption_Forecast_kW": row.get("forecast_consumption_kw"),
                }),
                completed,
            )
    return None


def _mode_from_label(mode_label: str) -> int:
    for mode_id, label in MODE_LABELS.items():
        if label == mode_label:
            return mode_id
    return 0


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
    """
    Produktiv-Einträge mit completed_at in [window_start, window_end).

    JSONL bevorzugt; Legacy-CSV nur für Zeitpunkte ohne JSONL-Eintrag.
    """
    merged = _merge_history_rows(_load_jsonl_history() + _load_legacy_csv_history())
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
    """Frühester bekanntes completed_at aus JSONL und Legacy-CSV."""
    merged = _merge_history_rows(_load_jsonl_history() + _load_legacy_csv_history())
    if not merged:
        return None
    return merged[0]["completed_at"]


@dataclass(frozen=True)
class ProductionLogSourceInfo:
    """Metadaten zur aktuell eingebundenen Produktiv-Log-Datei."""

    runtime_dir: str
    env_runtime_dir: str | None
    history_file: str
    history_exists: bool
    history_size_bytes: int | None
    history_modified_at: datetime | None
    legacy_csv_file: str
    legacy_csv_exists: bool


def describe_production_log_source() -> ProductionLogSourceInfo:
    """
    Beschreibt, welche Datei die UI für den Produktiv-Log liest.

    Entspricht ``HISTORY_FILE`` / ``RUNTIME_DIR`` zum Zeitpunkt des Aufrufs
    (Modul-Import cached die Pfade nicht — Streamlit-Reload übernimmt neue Env).
    """
    runtime_dir = os.path.abspath(RUNTIME_DIR)
    history_file = os.path.abspath(HISTORY_FILE)
    legacy_csv = os.path.abspath(LEGACY_CSV_FILE)
    history_exists = os.path.isfile(history_file)
    history_size: int | None = None
    history_mtime: datetime | None = None
    if history_exists:
        stat = os.stat(history_file)
        history_size = stat.st_size
        history_mtime = datetime.fromtimestamp(stat.st_mtime)
    return ProductionLogSourceInfo(
        runtime_dir=runtime_dir,
        env_runtime_dir=os.environ.get("ENERGY_OPTIMIZER_RUNTIME_DIR"),
        history_file=history_file,
        history_exists=history_exists,
        history_size_bytes=history_size,
        history_modified_at=history_mtime,
        legacy_csv_file=legacy_csv,
        legacy_csv_exists=os.path.isfile(legacy_csv),
    )
