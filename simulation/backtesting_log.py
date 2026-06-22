# backtesting_log.py
"""Persistenz und Laden der Backtesting-Ergebnisse für scripts/run_backtesting.py und app.py."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from file_metadata import (
    BACKTESTING_LOG_SCHEMA,
    read_schema_version,
    stamp_payload,
)

from .engine import (
    CONSUMPTION_TOLERANCE_KWH,
    CONSUMPTION_TOLERANCE_REL,
    HISTORICAL_REFERENCE_ID,
    PlausibilityReport,
)

logger = logging.getLogger(__name__)

BACKTESTING_LOG_JSON = "backtesting_log.json"
BACKTESTING_HOURLY_CSV = "backtesting_hourly.csv"
LOG_VERSION = BACKTESTING_LOG_SCHEMA


def _serialize_plausibility(report: PlausibilityReport) -> dict:
    return {
        "total_windows": len(report.results),
        "ok_count": len(report.results) - len(report.failed),
        "failed_count": len(report.failed),
        "tolerance_kwh": CONSUMPTION_TOLERANCE_KWH,
        "tolerance_rel": CONSUMPTION_TOLERANCE_REL,
        "failures": [
            {
                "window_end": r.window_end.isoformat(),
                "historical_kwh": r.historical_kwh,
                "optimized_kwh": r.optimized_kwh,
                "diff_kwh": r.diff_kwh,
            }
            for r in report.failed
        ],
    }


def _build_summary(results: dict[str, pd.DataFrame], labels: dict[str, str]) -> dict:
    total_eur = {
        scenario_id: round(float(df["sim_cost"].sum()), 4)
        for scenario_id, df in results.items()
    }
    monthly_eur: dict[str, dict[str, float]] = {}
    for scenario_id, df in results.items():
        label = labels.get(scenario_id, scenario_id)
        for period, value in df["sim_cost"].resample("ME").sum().items():
            month_key = pd.Timestamp(period).strftime("%Y-%m")
            monthly_eur.setdefault(month_key, {})[label] = round(float(value), 4)
    return {"total_eur": total_eur, "monthly_eur": monthly_eur}


def _hourly_to_csv(results: dict[str, pd.DataFrame], labels: dict[str, str]) -> pd.DataFrame:
    frames = []
    for scenario_id, df in results.items():
        part = df.copy()
        part.index.name = part.index.name or "ts"
        part.reset_index(inplace=True)
        if "index" in part.columns and "ts" not in part.columns:
            part.rename(columns={"index": "ts"}, inplace=True)
        part["scenario_id"] = scenario_id
        part["scenario_label"] = labels.get(scenario_id, scenario_id)
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    col_order = [
        "ts",
        "scenario_id",
        "scenario_label",
        "sim_cost",
        "sim_soc",
        "batt_action_kw",
        "steuerbefehl",
    ]
    return out[[c for c in col_order if c in out.columns]]


def save_backtesting_log(
    results: dict[str, pd.DataFrame],
    labels: dict[str, str],
    plausibility_by_scenario: dict[str, PlausibilityReport],
    period: dict,
    log_dir: str = ".",
) -> str:
    """Schreibt Metadaten (JSON) und Stundenwerte (CSV). Gibt den JSON-Pfad zurück."""
    os.makedirs(log_dir, exist_ok=True)
    json_path = os.path.join(log_dir, BACKTESTING_LOG_JSON)
    csv_path = os.path.join(log_dir, BACKTESTING_HOURLY_CSV)

    hourly_df = _hourly_to_csv(results, labels)
    hourly_df.to_csv(csv_path, index=False, sep=";", decimal=",")

    all_ts = []
    for df in results.values():
        if not df.empty:
            all_ts.extend(df.index.tolist())

    payload = stamp_payload(
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "period": period,
            "labels": labels,
            "summary": _build_summary(results, labels),
            "plausibility": {
                sid: _serialize_plausibility(rep)
                for sid, rep in plausibility_by_scenario.items()
            },
            "hourly_file": BACKTESTING_HOURLY_CSV,
            "scenario_ids": list(results.keys()),
            "reference_id": HISTORICAL_REFERENCE_ID,
        },
        schema_version=BACKTESTING_LOG_SCHEMA,
    )
    if all_ts:
        payload["period"]["first_ts"] = pd.Timestamp(min(all_ts)).isoformat()
        payload["period"]["last_ts"] = pd.Timestamp(max(all_ts)).isoformat()
        payload["period"]["hours"] = len(all_ts) // max(len(results), 1)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return json_path


def load_backtesting_log(log_dir: str = ".") -> tuple[dict, pd.DataFrame]:
    """
    Lädt Backtesting-Log.
    Returns: (metadata dict, hourly DataFrame mit allen Szenarien)
    """
    json_path = os.path.join(log_dir, BACKTESTING_LOG_JSON)
    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"Kein Backtesting-Log gefunden ({json_path}). "
            "Bitte zuerst scripts/run_backtesting.py ausführen."
        )

    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    schema_version = read_schema_version(meta, default=1)
    if schema_version > BACKTESTING_LOG_SCHEMA:
        logger.warning(
            "backtesting_log: neuere Schema-Version %s (aktuell %s) – lese best effort",
            schema_version,
            BACKTESTING_LOG_SCHEMA,
        )

    hourly_name = meta.get("hourly_file", BACKTESTING_HOURLY_CSV)
    csv_path = os.path.join(log_dir, hourly_name)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Stundendatei fehlt: {csv_path}")

    hourly = pd.read_csv(csv_path, sep=";", decimal=",")
    if "ts" in hourly.columns:
        hourly["ts"] = pd.to_datetime(hourly["ts"])
    return meta, hourly


def log_exists(log_dir: str = ".") -> bool:
    return os.path.exists(os.path.join(log_dir, BACKTESTING_LOG_JSON))
