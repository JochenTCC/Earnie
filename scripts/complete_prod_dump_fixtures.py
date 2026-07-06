#!/usr/bin/env python3
"""Ergänzt fehlende Dateien in tests/fixtures/prod_dumps/ aus optimization_history.jsonl."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = ROOT / "tests" / "fixtures" / "prod_dumps"

CASE_SPECS = {
    "eauto_deadline_missed_2026-06-27": {
        "state_prefix": "2026-06-27T05:00",
        "state_date": "2026-06-26",
        "run_state_prefix": "2026-06-27T09:30",
        "pv_written_at": "2026-06-27T09:31:12",
        "manual_state": {
            "schema_version": 2,
            "written_at": "2026-06-27T05:00:00",
            "written_by_app_version": "1.9.3",
            "date": "2026-06-26",
            "delivered": {"swimspa": 1.0},
            "charging_sessions": {
                "eauto": {
                    "target_kwh": 16.0,
                    "delivered_kwh": 2.0,
                    "deadline": "2026-06-27T09:30:00",
                }
            },
        },
        "manual_run_state": {
            "schema_version": 1,
            "source": "main.py",
            "success": True,
            "run_trigger": "event:eauto_ready_by",
            "written_by_app_version": "1.9.3",
            "soc_percent": 10.0,
            "charging_contexts": {
                "eauto": {
                    "active": True,
                    "plugged_in": True,
                    "deadline": "2026-06-27T09:30:00",
                    "target_kwh": 16.0,
                    "use_time_window": False,
                    "source_label": "loxone (Fertig-Uhrzeit)",
                }
            },
            "consumer_remaining_kwh": {"eauto": 9.4},
            "completed_at": "2026-06-27T09:30:02",
        },
    },
    "eauto_urgent_deferred_cheap_hours_2026-06-28": {
        "state_prefix": "2026-06-28T09:32",
        "state_date": "2026-06-28",
        "run_state_prefix": "2026-06-28T09:32",
        "pv_written_at": "2026-06-28T08:06:30",
    },
    "eauto_false_complete_2026-06-29": {
        "state_prefix": "2026-06-28T18:15",
        "state_date": "2026-06-28",
        "run_state_prefix": "2026-06-28T18:15",
        "pv_written_at": "2026-07-02T07:54:30",
    },
}


def _load_rows(case_dir: Path) -> list[dict]:
    history = case_dir / "optimization_history.jsonl"
    if not history.is_file():
        raise FileNotFoundError(f"{history} fehlt")
    rows: list[dict] = []
    for line in history.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            rows.append(json.loads(text))
    return rows


def _nearest_row(rows: list[dict], prefix: str) -> dict | None:
    matches = [row for row in rows if str(row.get("written_at", "")).startswith(prefix)]
    return matches[-1] if matches else None


def _build_consumer_state(row: dict, date_str: str) -> dict:
    ctx = (row.get("charging_contexts") or {}).get("eauto") or {}
    remaining = (row.get("consumer_remaining_kwh") or {}).get("eauto")
    delivered = None
    if ctx.get("target_kwh") is not None and remaining is not None:
        delivered = round(float(ctx["target_kwh"]) - float(remaining), 3)
    state = {
        "schema_version": 2,
        "written_at": row.get("written_at"),
        "written_by_app_version": row.get("written_by_app_version", ""),
        "date": date_str,
        "delivered": {},
        "charging_sessions": {},
    }
    if ctx.get("active") and ctx.get("deadline") and ctx.get("target_kwh"):
        deadline = ctx["deadline"]
        if not isinstance(deadline, str):
            deadline = str(deadline)[:19]
        state["charging_sessions"]["eauto"] = {
            "target_kwh": float(ctx["target_kwh"]),
            "delivered_kwh": max(0.0, delivered or 0.0),
            "deadline": deadline,
        }
    return state


def _build_run_state(row: dict) -> dict:
  state = dict(row)
  state.pop("written_at", None)
  state["completed_at"] = row.get("written_at")
  return state


def _build_pv_state(row: dict | None, *, written_at: str, app_version: str) -> dict:
    last_total = 0.0
    if row:
        snap = row.get("consumption_snapshot") or {}
        pv_kw = float(snap.get("pv_kw", 0.0) or 0.0)
        last_total = round(pv_kw * 1000.0 + 20000.0, 2)
    return {
        "schema_version": 1,
        "written_at": written_at,
        "written_by_app_version": app_version,
        "last_total_pv": last_total,
        "last_updated": written_at,
    }


def _write_json(path: Path, payload: dict, *, force: bool) -> bool:
    if path.is_file() and not force:
        return False
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return True


def complete_case(case_id: str, *, force: bool) -> list[str]:
    case_dir = FIXTURES_ROOT / case_id
    manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    spec = CASE_SPECS[case_id]
    rows = _load_rows(case_dir)
    written: list[str] = []

    state_row = _nearest_row(rows, spec["state_prefix"])
    if spec.get("manual_state"):
        state_payload = spec["manual_state"]
    elif state_row is not None:
        state_payload = _build_consumer_state(state_row, spec["state_date"])
    else:
        raise ValueError(f"{case_id}: kein History-Eintrag für {spec['state_prefix']!r}")

    if _write_json(case_dir / "flexible_consumers_state.json", state_payload, force=force):
        written.append("flexible_consumers_state.json")

    run_row = _nearest_row(rows, spec["run_state_prefix"])
    run_path = case_dir / "optimizer_run_state.json"
    if spec.get("manual_run_state"):
        run_payload = dict(spec["manual_run_state"])
    elif run_row is not None:
        run_payload = _build_run_state(run_row)
    else:
        run_payload = None

    if run_payload is not None:
        if _write_json(run_path, run_payload, force=force):
            written.append("optimizer_run_state.json")

    pv_row = run_row or state_row
    pv_payload = _build_pv_state(
        pv_row,
        written_at=spec["pv_written_at"],
        app_version=str(manifest.get("app_version", "")),
    )
    if _write_json(case_dir / "pv_counter_state.json", pv_payload, force=force):
        written.append("pv_counter_state.json")

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Bestehende Dateien überschreiben")
    args = parser.parse_args()

    for case_id in CASE_SPECS:
        created = complete_case(case_id, force=args.force)
        if created:
            print(f"{case_id}: {', '.join(created)}")
        else:
            print(f"{case_id}: nichts zu tun")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
