"""Compare SE calc runs: actual cons_data vs Live-ref vs optimized.

Writes docs/spec/se-calc-test-results.json and updates the results appendix
in docs/spec/se-calculation-test-plan.md.

Example:
  python -m scripts.se_calc_test_compare
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_APPENDIX_MARKER = "## Results appendix"
_TOL_REL = 0.05


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _rel_delta(actual: float | None, reference: float | None) -> float | None:
    if actual is None or reference is None:
        return None
    if abs(reference) < 1e-9:
        return None
    return round((actual - reference) / reference, 4)


def _status_for_row(
    *,
    b_gate: bool,
    actual_kwh: float | None,
    live_ref_kwh: float | None,
    optimized_kwh: float | None,
    ok_count: int | None,
    total_windows: int | None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    if b_gate:
        return "hard_fail", ["B-gate unexpectedly True"]
    if actual_kwh is None or live_ref_kwh is None or optimized_kwh is None:
        return "hard_fail", ["missing kWh artifacts"]

    opt_delta = _rel_delta(optimized_kwh, live_ref_kwh)
    act_delta = _rel_delta(actual_kwh, live_ref_kwh)
    if act_delta is not None and abs(act_delta) > _TOL_REL:
        notes.append(f"warn actual vs Live-ref |Δ|={abs(act_delta):.1%} > 5%")

    hard = False
    if opt_delta is not None and abs(opt_delta) > _TOL_REL:
        plaus_ok = (
            ok_count is not None
            and total_windows is not None
            and total_windows > 0
            and ok_count == total_windows
        )
        if plaus_ok:
            notes.append(
                f"timing-shift ok: optimized vs Live-ref |Δ|={abs(opt_delta):.1%}"
            )
        else:
            notes.append(
                f"optimized vs Live-ref |Δ|={abs(opt_delta):.1%} unexplained"
            )
            hard = True

    if hard:
        return "hard_fail", notes
    if notes:
        return "warn", notes
    return "pass", notes


def _load_run_metrics(log_path: Path, live_id: str) -> dict:
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    period = payload.get("period") or {}
    plaus = payload.get("plausibility") or {}
    live_block = plaus.get(live_id) or {}
    totals = live_block.get("consumption_totals") or {}
    return {
        "period": period,
        "historical_kwh": totals.get("historical_kwh"),
        "optimized_kwh": totals.get("optimized_kwh"),
        "ok_count": live_block.get("ok_count"),
        "total_windows": live_block.get("total_windows"),
        "failed_count": live_block.get("failed_count"),
        "log_path": str(log_path),
    }


def _actual_kwh(period: dict) -> float | None:
    from data import cons_data_store
    from ui.backtesting_results_helpers import reference_kwh_for_period

    if not cons_data_store.is_cons_data_populated():
        return None
    cons_df = cons_data_store.load_cons_data()
    if cons_df is None or getattr(cons_df, "empty", True):
        return None
    return reference_kwh_for_period(cons_df, period)


def _period_for_month(year: int, month: int) -> dict:
    start = pd.Timestamp(year, month, 1)
    end = (start + pd.offsets.MonthEnd(0)).normalize()
    return {
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "start_month": month,
        "end_month": month,
        "backtesting_year": year,
    }


def _collect_rows(descriptors: dict, year: int, months: list[int]) -> list[dict]:
    from scripts.se_calc_test_common import run_output_dir

    live_id = (descriptors.get("inventory") or {}).get("live_scenario_id") or "live"
    rows: list[dict] = []
    for cell_id, meta in (descriptors.get("cells") or {}).items():
        if meta.get("skipped"):
            rows.append(
                {
                    "cell": cell_id,
                    "status": "skipped",
                    "notes": [meta.get("skip_reason") or "skipped"],
                }
            )
            continue
        b_gate = bool(meta.get("b_gate"))
        for month in months:
            log_path = run_output_dir(cell_id, year, month) / "backtesting_log.json"
            if not log_path.is_file():
                rows.append(
                    {
                        "cell": cell_id,
                        "year": year,
                        "month": month,
                        "status": "hard_fail",
                        "notes": [f"missing {log_path}"],
                        "b_gate": b_gate,
                    }
                )
                continue
            metrics = _load_run_metrics(log_path, live_id)
            period = metrics.get("period") or _period_for_month(year, month)
            actual = _actual_kwh(period)
            live_ref = metrics.get("historical_kwh")
            optimized = metrics.get("optimized_kwh")
            status, notes = _status_for_row(
                b_gate=b_gate,
                actual_kwh=actual,
                live_ref_kwh=live_ref,
                optimized_kwh=optimized,
                ok_count=metrics.get("ok_count"),
                total_windows=metrics.get("total_windows"),
            )
            rows.append(
                {
                    "cell": cell_id,
                    "year": year,
                    "month": month,
                    "b_gate": b_gate,
                    "actual_kwh": actual,
                    "live_ref_kwh": live_ref,
                    "optimized_kwh": optimized,
                    "delta_actual_vs_ref_rel": _rel_delta(actual, live_ref),
                    "delta_opt_vs_ref_rel": _rel_delta(optimized, live_ref),
                    "ok_count": metrics.get("ok_count"),
                    "total_windows": metrics.get("total_windows"),
                    "failed_count": metrics.get("failed_count"),
                    "status": status,
                    "notes": notes,
                    "log_path": metrics.get("log_path"),
                    "period": period,
                }
            )
    return rows


def _markdown_table(rows: list[dict]) -> str:
    lines = [
        "| Cell | Month | Actual kWh | Live-ref kWh | Optimized kWh | Δ act/ref | Δ opt/ref | Status | Notes |",
        "| ---- | ----- | ---------- | ------------ | ------------- | --------- | --------- | ------ | ----- |",
    ]
    for row in rows:
        if row.get("status") == "skipped":
            lines.append(
                f"| {row.get('cell')} | — | — | — | — | — | — | skipped | "
                f"{'; '.join(row.get('notes') or [])} |"
            )
            continue
        month = row.get("month")
        year = row.get("year")
        month_label = f"{int(month):02d}/{year}" if month and year else "—"

        def _f(key: str) -> str:
            val = row.get(key)
            if val is None:
                return "—"
            if key.endswith("_rel"):
                return f"{val:+.1%}"
            return f"{float(val):.1f}"

        notes = "; ".join(row.get("notes") or []) or "—"
        lines.append(
            f"| {row.get('cell')} | {month_label} | {_f('actual_kwh')} | "
            f"{_f('live_ref_kwh')} | {_f('optimized_kwh')} | "
            f"{_f('delta_actual_vs_ref_rel')} | {_f('delta_opt_vs_ref_rel')} | "
            f"{row.get('status')} | {notes} |"
        )
    return "\n".join(lines)


def _update_plan_appendix(table_md: str, summary_note: str) -> None:
    from scripts.se_calc_test_common import RESULTS_MD_ANCHOR

    path = RESULTS_MD_ANCHOR
    text = path.read_text(encoding="utf-8")
    idx = text.find(_APPENDIX_MARKER)
    if idx < 0:
        raise RuntimeError(f"Missing '{_APPENDIX_MARKER}' in {path}")
    head = text[: idx + len(_APPENDIX_MARKER)]
    body = (
        "\n\nFilled by `scripts/se_calc_test_compare.py`.\n\n"
        f"{summary_note}\n\n"
        f"{table_md}\n\n"
        "Machine-readable: [se-calc-test-results.json](se-calc-test-results.json).\n"
    )
    path.write_text(head + body, encoding="utf-8")  # NOSONAR pythonsecurity:S8707


def _summary_note(rows: list[dict]) -> str:
    warns = sum(1 for r in rows if r.get("status") == "warn")
    fails = sum(1 for r in rows if r.get("status") == "hard_fail")
    return (
        "**Notes from this run:** M0 ≡ M1 for Live-ref/optimized (path **A** ignores "
        "`total_profile_csv` for Basislast). M2 shifts Live-ref when thermal/EV CSV "
        f"overlays are on. Summary: {warns} warn, {fails} hard_fail "
        "(warn = actual vs Live-ref >5%, not auto-fail)."
    )


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    from scripts.se_calc_test_common import (
        DEFAULT_YEAR,
        DESCRIPTORS_PATH,
        RESULTS_JSON,
        RESULTS_MD_ANCHOR,
        SEASONAL_MONTHS,
        load_json,
        parse_months,
        write_json,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--months", default=",".join(str(m) for m in SEASONAL_MONTHS))
    args = parser.parse_args(argv)

    if not DESCRIPTORS_PATH.is_file():
        print(f"Missing descriptors: {DESCRIPTORS_PATH}", file=sys.stderr)
        print("Run: python -m scripts.se_calc_test_matrix --cells M0,M1,M2", file=sys.stderr)
        return 2

    descriptors = load_json(DESCRIPTORS_PATH)
    months = parse_months(args.months)
    rows = _collect_rows(descriptors, args.year, months)
    payload = {
        "year": args.year,
        "months": months,
        "inventory": descriptors.get("inventory"),
        "rows": rows,
        "summary": {
            "pass": sum(1 for r in rows if r.get("status") == "pass"),
            "warn": sum(1 for r in rows if r.get("status") == "warn"),
            "hard_fail": sum(1 for r in rows if r.get("status") == "hard_fail"),
            "skipped": sum(1 for r in rows if r.get("status") == "skipped"),
        },
    }
    write_json(RESULTS_JSON, payload)
    table = _markdown_table(rows)
    note = _summary_note(rows)
    _update_plan_appendix(table, note)
    print(table)
    print(f"\nWrote {RESULTS_JSON}")
    print(f"Updated appendix in {RESULTS_MD_ANCHOR}")
    if payload["summary"]["hard_fail"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
