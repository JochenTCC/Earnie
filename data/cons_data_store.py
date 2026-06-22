"""
cons_data_store.py – Lesen/Schreiben der generischen Stunden-Log-Datei (cons_data_hourly.csv).

Wird von profile_manager, main.py und scripts/generate_cons_data.py genutzt.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

import config
from runtime_store.file_metadata import (
    CONS_DATA_META_SCHEMA,
    CONS_DATA_PENDING_SCHEMA,
    read_schema_version,
    stamp_payload,
    strip_metadata,
)

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = "cons_data_hourly.csv"
METADATA_SUFFIX = ".meta.json"
PENDING_STATE_FILE = "cons_data_pending.json"
CSV_SEP = ";"
SOURCE_LOXONE = "loxone"
SOURCE_SYNTHETIC = "synthetic"
SOURCE_MEASURED = "measured"


def get_output_path() -> str:
    sim = config.get_file_paths_battery_simulation()
    return sim.get("path_cons_data") or DEFAULT_OUTPUT


def get_retention_months() -> int:
    sim = config.get_file_paths_battery_simulation()
    value = sim.get("cons_data_retention_months", 24)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 24


def get_write_mode() -> str:
    """hourly | daily – wie gemessene Stunden in die CSV geschrieben werden."""
    sim = config.get_file_paths_battery_simulation()
    mode = str(sim.get("cons_data_write_mode", "hourly")).strip().lower()
    return mode if mode in ("hourly", "daily") else "hourly"


def _consumer_column_ids() -> list[str]:
    return [c["id"] for c in config.get_flexible_consumers()]


def trim_retention(df: pd.DataFrame, months: int | None = None) -> pd.DataFrame:
    """Begrenzt die Historie auf die letzten N Monate (0 = unbegrenzt)."""
    if df.empty or months is None:
        months = get_retention_months()
    if months <= 0:
        return df
    cutoff = df.index.max() - pd.DateOffset(months=months)
    trimmed = df[df.index >= cutoff]
    if len(trimmed) < len(df):
        logger.info(
            "cons_data: Retention %s Monate – %s -> %s Stunden",
            months,
            len(df),
            len(trimmed),
        )
    return trimmed


def _normalize_cons_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    if "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame braucht Spalte 'timestamp' oder DatetimeIndex.")

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    for col in ("total_kw", "baseload_kw", "pv_kw"):
        if col not in df.columns:
            df[col] = 0.0

    for cid in _consumer_column_ids():
        col = f"{cid}_kw"
        if col not in df.columns:
            df[col] = 0.0

    flex_cols = [f"{cid}_kw" for cid in _consumer_column_ids()]
    numeric_cols = ["total_kw", "baseload_kw", "pv_kw", *flex_cols]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).round(3)

    if "source" not in df.columns:
        df["source"] = SOURCE_SYNTHETIC
    df["source"] = df["source"].astype(str)

    flex_sum = df[flex_cols].sum(axis=1) if flex_cols else 0.0
    inferred_baseload = (df["total_kw"] - flex_sum).clip(lower=0.0)
    mask = df["baseload_kw"].isna() | ((df["baseload_kw"] == 0.0) & (df["total_kw"] > 0))
    df.loc[mask, "baseload_kw"] = inferred_baseload.loc[mask]

    return df


def load_cons_data(path: str | None = None) -> pd.DataFrame:
    path = path or get_output_path()
    if not os.path.exists(path):
        return pd.DataFrame()

    df = pd.read_csv(path, sep=CSV_SEP, decimal=".")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return _normalize_cons_dataframe(df.set_index("timestamp"))


def save_cons_data(df: pd.DataFrame, path: str | None = None, *, apply_retention: bool = True) -> str:
    path = path or get_output_path()
    df = _normalize_cons_dataframe(df)
    if apply_retention:
        df = trim_retention(df)

    export = df.reset_index()
    export["timestamp"] = export["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    export.to_csv(path, sep=CSV_SEP, index=False, decimal=".")

    meta_path = path.replace(".csv", METADATA_SUFFIX) if path.endswith(".csv") else path + METADATA_SUFFIX
    meta = stamp_payload(
        {
            "output_file": path,
            "retention_months": get_retention_months(),
            "consumer_ids": _consumer_column_ids(),
            "date_range": {"min": str(df.index.min()), "max": str(df.index.max())},
            "row_count": len(df),
            "source_counts": df["source"].value_counts().to_dict() if not df.empty else {},
        },
        schema_version=CONS_DATA_META_SCHEMA,
    )
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return path


def append_measured_hours(
    new_rows: pd.DataFrame | list[dict],
    path: str | None = None,
) -> pd.DataFrame:
    path = path or get_output_path()
    existing = load_cons_data(path)

    if isinstance(new_rows, list):
        incoming = pd.DataFrame(new_rows)
    else:
        incoming = new_rows.copy()

    if incoming.empty:
        return existing

    if "timestamp" not in incoming.columns:
        raise ValueError("new_rows braucht eine Spalte 'timestamp'.")

    incoming["timestamp"] = pd.to_datetime(incoming["timestamp"])
    incoming = incoming.set_index("timestamp")
    incoming["source"] = SOURCE_MEASURED
    incoming = _normalize_cons_dataframe(incoming)

    if existing.empty:
        merged = incoming
    else:
        merged = pd.concat([existing, incoming])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()

    save_cons_data(merged, path)
    return merged


def build_hour_row_from_measurements(
    hour_start: datetime,
    total_kw: float,
    baseload_kw: float | None = None,
    pv_kw: float = 0.0,
    flex_kw: dict[str, float] | None = None,
) -> dict:
    flex_kw = flex_kw or {}
    flex_sum = sum(flex_kw.values())
    if baseload_kw is None:
        baseload_kw = max(0.0, total_kw - flex_sum)
    row = {
        "timestamp": hour_start.replace(minute=0, second=0, microsecond=0),
        "total_kw": round(total_kw, 3),
        "baseload_kw": round(baseload_kw, 3),
        "pv_kw": round(pv_kw, 3),
        "source": SOURCE_MEASURED,
    }
    for cid in _consumer_column_ids():
        row[f"{cid}_kw"] = round(float(flex_kw.get(cid, 0.0)), 3)
    return row


def get_date_bounds() -> tuple[datetime | None, datetime | None]:
    df = load_cons_data()
    if df.empty:
        return None, None
    return df.index.min(), df.index.max()


# ---------------------------------------------------------------------------
# Live-Sampling (main.py): Pro Durchlauf sammeln, stündlich/täglich flushen
# ---------------------------------------------------------------------------

def _load_pending_state() -> dict:
    if not os.path.exists(PENDING_STATE_FILE):
        return {"samples": [], "last_daily_flush": None}
    try:
        with open(PENDING_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        schema_version = read_schema_version(data, default=1)
        if schema_version > CONS_DATA_PENDING_SCHEMA:
            logger.warning(
                "cons_data pending: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                CONS_DATA_PENDING_SCHEMA,
            )
        payload = strip_metadata(data)
        if "samples" not in payload:
            payload["samples"] = []
        return payload
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("cons_data pending state unreadable: %s", e)
        return {"samples": [], "last_daily_flush": None}


def _save_pending_state(state: dict) -> None:
    payload = stamp_payload(strip_metadata(state), schema_version=CONS_DATA_PENDING_SCHEMA)
    with open(PENDING_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def record_live_sample(
    *,
    total_kw: float | None,
    pv_kwh_interval: float,
    flex_kw: dict[str, float] | None = None,
    sample_time: datetime | None = None,
) -> None:
    """Speichert einen Messpunkt aus einem main.py-Durchlauf (RAM + pending JSON)."""
    if total_kw is None:
        return

    sample_time = (sample_time or datetime.now()).replace(second=0, microsecond=0)
    state = _load_pending_state()
    state["samples"].append(
        {
            "ts": sample_time.isoformat(timespec="minutes"),
            "total_kw": round(float(total_kw), 3),
            "pv_kwh": round(max(0.0, float(pv_kwh_interval)), 4),
            "flex_kw": {k: round(float(v), 3) for k, v in (flex_kw or {}).items()},
        }
    )
    _save_pending_state(state)


def _aggregate_samples_to_hours(samples: Iterable[dict]) -> list[dict]:
    """Mittelt Leistungs-Samples pro Stunde; summiert PV-kWh-Intervalle."""
    buckets: dict[datetime, dict] = {}

    for sample in samples:
        ts = pd.to_datetime(sample["ts"]).to_pydatetime().replace(minute=0, second=0, microsecond=0)
        bucket = buckets.setdefault(
            ts,
            {"total_kw": [], "pv_kwh": 0.0, "flex_kw": {cid: [] for cid in _consumer_column_ids()}},
        )
        bucket["total_kw"].append(float(sample["total_kw"]))
        bucket["pv_kwh"] += float(sample.get("pv_kwh", 0.0))
        for cid, val in (sample.get("flex_kw") or {}).items():
            if cid in bucket["flex_kw"]:
                bucket["flex_kw"][cid].append(float(val))

    rows = []
    for hour_start, bucket in sorted(buckets.items()):
        total = round(sum(bucket["total_kw"]) / len(bucket["total_kw"]), 3)
        flex = {
            cid: round(sum(vals) / len(vals), 3) if vals else 0.0
            for cid, vals in bucket["flex_kw"].items()
        }
        rows.append(
            build_hour_row_from_measurements(
                hour_start,
                total_kw=total,
                pv_kw=round(bucket["pv_kwh"], 3),
                flex_kw=flex,
            )
        )
    return rows


def flush_pending_samples(now: datetime | None = None) -> int:
    """
    Schreibt abgeschlossene Stunden aus dem Pending-Puffer nach cons_data_hourly.csv.
    hourly: alle vollständigen Stunden vor der aktuellen
    daily: einmal pro Tag alle Stunden des Vortags (und älter)
    Returns: Anzahl geschriebener Stunden.
    """
    now = now or datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    today = now.date()
    mode = get_write_mode()

    state = _load_pending_state()
    samples = state.get("samples") or []
    if not samples:
        return 0

    if mode == "daily":
        last_flush = state.get("last_daily_flush")
        if last_flush == str(today):
            return 0
        eligible = [
            s
            for s in samples
            if pd.to_datetime(s["ts"]).date() < today
        ]
        remaining = [
            s
            for s in samples
            if pd.to_datetime(s["ts"]).date() >= today
        ]
    else:
        eligible = [
            s
            for s in samples
            if pd.to_datetime(s["ts"]).replace(minute=0, second=0, microsecond=0) < current_hour
        ]
        remaining = [
            s
            for s in samples
            if pd.to_datetime(s["ts"]).replace(minute=0, second=0, microsecond=0) >= current_hour
        ]

    if not eligible:
        return 0

    rows = _aggregate_samples_to_hours(eligible)
    if rows:
        append_measured_hours(rows)
        logger.info("cons_data: %s gemessene Stunde(n) geschrieben (%s-Modus).", len(rows), mode)

    state["samples"] = remaining
    if mode == "daily":
        state["last_daily_flush"] = str(today)
    _save_pending_state(state)
    return len(rows)


def record_and_maybe_flush(
    *,
    total_kw: float | None,
    pv_kwh_interval: float,
    flex_kw: dict[str, float] | None = None,
    sample_time: datetime | None = None,
) -> int:
    """Ein Aufruf pro main.py-Durchlauf: Sample speichern und ggf. flushen."""
    record_live_sample(
        total_kw=total_kw,
        pv_kwh_interval=pv_kwh_interval,
        flex_kw=flex_kw,
        sample_time=sample_time,
    )
    return flush_pending_samples(sample_time)
