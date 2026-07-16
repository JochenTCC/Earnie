# backtesting_log.py
"""Persistenz und Laden der Backtesting-Ergebnisse für scripts/run_backtesting.py und app.py."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from runtime_store.file_metadata import (
    BACKTESTING_LOG_SCHEMA,
    read_schema_version,
    stamp_payload,
)
from runtime_store.persist_paths import resolve_backtesting_log_dir

from .engine import (
    CONSUMPTION_TOLERANCE_KWH,
    CONSUMPTION_TOLERANCE_REL,
    HISTORICAL_REFERENCE_ID,
    PlausibilityReport,
    PlausibilityResult,
)
from .backtesting_snapshots import (
    BACKTESTING_WINDOW_SNAPSHOTS_JSONL,
    remove_window_snapshots_jsonl,
    write_window_snapshots_jsonl,
)

logger = logging.getLogger(__name__)

BACKTESTING_LOG_JSON = "backtesting_log.json"
BACKTESTING_HOURLY_CSV = "backtesting_hourly.csv"
BACKTESTING_CBC_EVENTS_JSONL = "backtesting_cbc_events.jsonl"
LOG_VERSION = BACKTESTING_LOG_SCHEMA
_DEFAULT_LOG_DIR = resolve_backtesting_log_dir()


def _compute_config_fingerprint(period: dict) -> str:
    from simulation.backtesting_fingerprint import fingerprint_for_current_config

    return fingerprint_for_current_config(period=period)


def consumption_totals_from_report(report: PlausibilityReport) -> dict:
    """Summiert historischen und optimierten Verbrauch über alle 24h-Fenster."""
    if not report.results:
        return {}
    historical = round(sum(r.historical_kwh for r in report.results), 1)
    optimized = round(sum(r.optimized_kwh for r in report.results), 1)
    payload: dict = {
        "historical_kwh": historical,
        "optimized_kwh": optimized,
        "delta_kwh": round(optimized - historical, 1),
    }
    if report.results[0].historical_baseload_kwh is not None:
        payload["historical_baseload_kwh"] = round(
            sum(r.historical_baseload_kwh or 0.0 for r in report.results), 1
        )
        payload["optimized_baseload_kwh"] = round(
            sum(r.optimized_baseload_kwh or 0.0 for r in report.results), 1
        )
        payload["historical_flex_kwh"] = round(
            sum(r.historical_flex_kwh or 0.0 for r in report.results), 1
        )
        payload["optimized_flex_kwh"] = round(
            sum(r.optimized_flex_kwh or 0.0 for r in report.results), 1
        )
    return payload


def _serialize_plausibility(report: PlausibilityReport) -> dict:
    totals = consumption_totals_from_report(report)
    return {
        "total_windows": len(report.results),
        "ok_count": len(report.results) - len(report.failed),
        "failed_count": len(report.failed),
        "tolerance_kwh": CONSUMPTION_TOLERANCE_KWH,
        "tolerance_rel": CONSUMPTION_TOLERANCE_REL,
        **({"consumption_totals": totals} if totals else {}),
        "failures": [
            {
                "window_end": r.window_end.isoformat(),
                "historical_kwh": r.historical_kwh,
                "optimized_kwh": r.optimized_kwh,
                "diff_kwh": r.diff_kwh,
                **(
                    {
                        "historical_baseload_kwh": r.historical_baseload_kwh,
                        "optimized_baseload_kwh": r.optimized_baseload_kwh,
                        "historical_flex_kwh": r.historical_flex_kwh,
                        "optimized_flex_kwh": r.optimized_flex_kwh,
                        "baseload_diff_kwh": r.baseload_diff_kwh,
                        "flex_diff_kwh": r.flex_diff_kwh,
                    }
                    if r.baseload_diff_kwh is not None
                    else {}
                ),
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
    base_order = [
        "ts",
        "scenario_id",
        "scenario_label",
        "consumption_kw",
        "baseload_kw",
    ]
    flex_cols = sorted(
        col
        for col in out.columns
        if col.endswith("_kw")
        and col not in {"consumption_kw", "baseload_kw", "batt_action_kw"}
    )
    tail_order = ["sim_cost", "sim_soc", "batt_action_kw", "steuerbefehl"]
    col_order = base_order + flex_cols + tail_order
    return out[[c for c in col_order if c in out.columns]]


def _summarize_cbc_events(events_by_scenario: dict[str, list[dict]]) -> dict:
    summary: dict[str, dict[str, int]] = {}
    for scenario_id, events in events_by_scenario.items():
        counts: dict[str, int] = {}
        for event in events:
            kind = str(event.get("event", "unknown"))
            counts[kind] = counts.get(kind, 0) + 1
        summary[scenario_id] = counts
    return summary


def _plausibility_failure_cases(
    plausibility_by_scenario: dict[str, PlausibilityReport],
) -> list[dict]:
    cases: list[dict] = []
    for scenario_id, report in plausibility_by_scenario.items():
        for result in report.failed:
            cases.append(
                {
                    "kind": "consumption_tolerance",
                    "scenario_id": scenario_id,
                    "window_anchor": result.window_end.isoformat(),
                    "historical_kwh": result.historical_kwh,
                    "optimized_kwh": result.optimized_kwh,
                    "diff_kwh": result.diff_kwh,
                }
            )
    return cases


def _plausibility_lookup(
    plausibility_by_scenario: dict[str, PlausibilityReport],
) -> dict[tuple[str, str], PlausibilityResult]:
    lookup: dict[tuple[str, str], PlausibilityResult] = {}
    for scenario_id, report in plausibility_by_scenario.items():
        for result in report.results:
            lookup[(scenario_id, result.window_end.isoformat())] = result
    return lookup


def _cbc_event_cases(
    cbc_events_by_scenario: dict[str, list[dict]],
    *,
    plausibility_lookup: dict[tuple[str, str], PlausibilityResult] | None = None,
) -> list[dict]:
    cases: list[dict] = []
    for scenario_id, events in cbc_events_by_scenario.items():
        for event in events:
            case = {
                "kind": str(event.get("event", "cbc_unknown")),
                "scenario_id": scenario_id,
                "window_anchor": event.get("window_anchor"),
                "slot_datetime": event.get("slot_datetime"),
                "simulation_hour_index": event.get("simulation_hour_index"),
                "milp_hour": event.get("milp_hour"),
                "consumer_targets_kwh": event.get("consumer_targets_kwh"),
                "strict_limit_sec": event.get("strict_limit_sec"),
                "strict_elapsed_sec": event.get("strict_elapsed_sec"),
                "strict_status": event.get("strict_status"),
                "final_status": event.get("final_status"),
                "gap_rel": event.get("gap_rel"),
            }
            if plausibility_lookup is not None:
                plaus = plausibility_lookup.get(
                    (scenario_id, str(event.get("window_anchor") or ""))
                )
                if plaus is not None:
                    case["window_consumption_diff_kwh"] = plaus.diff_kwh
                    case["window_consumption_ok"] = plaus.ok
            cases.append(case)
    return cases


def _critical_case_sort_key(case: dict) -> tuple:
    return (
        case.get("window_anchor") or "",
        case.get("slot_datetime") or "",
        case.get("simulation_hour_index") if case.get("simulation_hour_index") is not None else -1,
        case.get("kind") or "",
    )


KIND_CRITICALITY_ORDER: dict[str, int] = {
    "milp_no_optimal": 0,
    "strict_slow": 1,
    "strict_fallback": 2,
    "consumption_tolerance": 3,
}


def _case_severity_key(case: dict) -> tuple[int, float]:
    """Niedrigerer Wert = kritischer (für Dedup pro Fenster)."""
    kind = str(case.get("kind", "unknown"))
    priority = KIND_CRITICALITY_ORDER.get(kind, 99)
    if kind == "consumption_tolerance":
        metric = abs(float(case.get("diff_kwh") or 0.0))
    elif kind in {"strict_slow", "strict_fallback"}:
        metric = float(
            case.get("strict_elapsed_sec")
            or case.get("gap_rel")
            or 0.0
        )
    else:
        metric = 0.0
    return priority, -metric


def dedupe_critical_cases_by_window(cases: list[dict]) -> list[dict]:
    """Behält pro (Szenario, Fenster) nur den kritischsten Eintrag."""
    without_anchor: list[dict] = []
    best_by_key: dict[tuple[str, str], dict] = {}
    for case in cases:
        anchor = case.get("window_anchor")
        if not anchor:
            without_anchor.append(case)
            continue
        key = (str(case.get("scenario_id", "?")), str(anchor))
        existing = best_by_key.get(key)
        if existing is None or _case_severity_key(case) < _case_severity_key(existing):
            best_by_key[key] = case
    deduped = list(best_by_key.values()) + without_anchor
    return sorted(deduped, key=_critical_case_sort_key)


def build_critical_cases(
    plausibility_by_scenario: dict[str, PlausibilityReport],
    cbc_events_by_scenario: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Vereinigt Verbrauchstoleranz-Verletzungen und CBC-/MILP-Ereignisse."""
    plausibility_lookup = _plausibility_lookup(plausibility_by_scenario)
    cases = _plausibility_failure_cases(plausibility_by_scenario)
    if cbc_events_by_scenario:
        cases.extend(
            _cbc_event_cases(
                cbc_events_by_scenario,
                plausibility_lookup=plausibility_lookup,
            )
        )
    return sorted(cases, key=_critical_case_sort_key)


def summarize_critical_cases(cases: list[dict]) -> dict:
    by_kind: dict[str, int] = {}
    by_scenario: dict[str, int] = {}
    windows: set[tuple[str, str]] = set()
    for case in cases:
        kind = str(case.get("kind", "unknown"))
        scenario_id = str(case.get("scenario_id", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_scenario[scenario_id] = by_scenario.get(scenario_id, 0) + 1
        anchor = case.get("window_anchor")
        if anchor:
            windows.add((scenario_id, str(anchor)))
    return {
        "total": len(cases),
        "distinct_windows": len(windows),
        "by_kind": by_kind,
        "by_scenario": by_scenario,
    }


def extract_critical_cases(meta: dict) -> list[dict]:
    """
    Liest kritische Fälle aus backtesting_log.json (neu: critical_cases,
    sonst aus plausibility.failures + cbc_events_by_scenario).
    """
    if "critical_cases" in meta:
        return list(meta["critical_cases"])
    cases = []
    for scenario_id, block in meta.get("plausibility", {}).items():
        for failure in block.get("failures", []):
            cases.append(
                {
                    "kind": "consumption_tolerance",
                    "scenario_id": scenario_id,
                    "window_anchor": failure.get("window_end"),
                    "historical_kwh": failure.get("historical_kwh"),
                    "optimized_kwh": failure.get("optimized_kwh"),
                    "diff_kwh": failure.get("diff_kwh"),
                }
            )
    cases.extend(_cbc_event_cases(meta.get("cbc_events_by_scenario", {})))
    return sorted(cases, key=_critical_case_sort_key)


def _append_cbc_events_jsonl(
    log_dir: str,
    events_by_scenario: dict[str, list[dict]],
    period: dict,
) -> str:
    path = os.path.join(log_dir, BACKTESTING_CBC_EVENTS_JSONL)
    run_meta = {
        "period_start": period.get("start"),
        "period_end": period.get("end"),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "a", encoding="utf-8") as f:
        for scenario_id, events in events_by_scenario.items():
            for event in events:
                line = {**run_meta, **event, "scenario_id": scenario_id}
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def save_backtesting_log(
    results: dict[str, pd.DataFrame],
    labels: dict[str, str],
    plausibility_by_scenario: dict[str, PlausibilityReport],
    period: dict,
    log_dir: str | None = None,
    cbc_events_by_scenario: dict[str, list[dict]] | None = None,
    config_fingerprint: str | None = None,
    window_snapshots: list[dict] | None = None,
) -> str:
    """Schreibt Metadaten (JSON) und Stundenwerte (CSV). Gibt den JSON-Pfad zurück."""
    target_dir = _DEFAULT_LOG_DIR if log_dir is None else log_dir
    os.makedirs(target_dir, exist_ok=True)
    json_path = os.path.join(target_dir, BACKTESTING_LOG_JSON)
    csv_path = os.path.join(target_dir, BACKTESTING_HOURLY_CSV)

    hourly_df = _hourly_to_csv(results, labels)
    hourly_df.to_csv(csv_path, index=False, sep=";", decimal=",")

    all_ts = []
    for df in results.values():
        if not df.empty:
            for ts in df.index.tolist():
                stamp = pd.Timestamp(ts)
                if stamp.tzinfo is not None:
                    stamp = stamp.tz_localize(None)
                all_ts.append(stamp)

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
            "config_fingerprint": config_fingerprint or _compute_config_fingerprint(period),
        },
        schema_version=BACKTESTING_LOG_SCHEMA,
    )
    if cbc_events_by_scenario:
        payload["cbc_events_by_scenario"] = cbc_events_by_scenario
        payload["cbc_events_summary"] = _summarize_cbc_events(cbc_events_by_scenario)
        payload["cbc_events_file"] = BACKTESTING_CBC_EVENTS_JSONL
        _append_cbc_events_jsonl(target_dir, cbc_events_by_scenario, period)
    critical_cases = build_critical_cases(
        plausibility_by_scenario,
        cbc_events_by_scenario,
    )
    payload["critical_cases"] = critical_cases
    payload["critical_cases_summary"] = summarize_critical_cases(critical_cases)
    if window_snapshots:
        snapshots_path = write_window_snapshots_jsonl(target_dir, window_snapshots)
        if snapshots_path:
            payload["window_snapshots_file"] = BACKTESTING_WINDOW_SNAPSHOTS_JSONL
            payload["window_snapshots_count"] = len(window_snapshots)
            payload["window_snapshots_horizon_mode"] = period.get("horizon_mode")
    else:
        remove_window_snapshots_jsonl(target_dir)
    if all_ts:
        payload["period"]["first_ts"] = pd.Timestamp(min(all_ts)).isoformat()
        payload["period"]["last_ts"] = pd.Timestamp(max(all_ts)).isoformat()
        payload["period"]["hours"] = len(all_ts) // max(len(results), 1)
    if period.get("reference_by_scenario"):
        payload["reference_by_scenario"] = period["reference_by_scenario"]

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return json_path


def load_backtesting_log(log_dir: str | None = None) -> tuple[dict, pd.DataFrame]:
    """
    Lädt Backtesting-Log.
    Returns: (metadata dict, hourly DataFrame mit allen Szenarien)
    """
    target_dir = _DEFAULT_LOG_DIR if log_dir is None else log_dir
    json_path = os.path.join(target_dir, BACKTESTING_LOG_JSON)
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
    csv_path = os.path.join(target_dir, hourly_name)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Stundendatei fehlt: {csv_path}")

    hourly = pd.read_csv(csv_path, sep=";", decimal=",")
    if "ts" in hourly.columns:
        hourly["ts"] = pd.to_datetime(hourly["ts"])
    return meta, hourly


def backtesting_log_json_path(log_dir: str | None = None) -> str:
    """Absoluter Pfad zu backtesting_log.json im Backtesting-Ausgabeordner."""
    target_dir = _DEFAULT_LOG_DIR if log_dir is None else log_dir
    return os.path.join(target_dir, BACKTESTING_LOG_JSON)


def log_exists(log_dir: str | None = None) -> bool:
    return os.path.exists(backtesting_log_json_path(log_dir))
