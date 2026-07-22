"""Compare SE backtesting runs for different commit_hours (K=1 / 6 / 24).

Reads backtesting_log.json (+ optional hourly CSV and wall_time.json) from
sibling k{N}/ directories and writes Markdown + CSV summaries.

Example:
  python -m scripts.compare_commit_hours_backtests \\
    --run-root backtesting_logs/commit_hours_compare_2026-03/fixed_24h \\
    -o backtesting_logs/commit_hours_compare_2026-03/fixed_24h/comparison.md
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _plaus_ok(plausibility: dict, scenario_id: str) -> str:
    report = plausibility.get(scenario_id) or {}
    total = report.get("total_windows", 0)
    ok = report.get("ok_count", 0)
    return f"{ok}/{total}"


def _battery_totals(hourly_csv: Path | None, scenario_id: str) -> dict[str, float]:
    if hourly_csv is None or not hourly_csv.is_file():
        return {"charge_kwh": 0.0, "discharge_kwh": 0.0}
    import pandas as pd

    df = pd.read_csv(hourly_csv, sep=";")
    mask = df["scenario_id"] == scenario_id
    if "batt_action_kw" not in df.columns:
        return {"charge_kwh": 0.0, "discharge_kwh": 0.0}
    batt = pd.to_numeric(df.loc[mask, "batt_action_kw"], errors="coerce").fillna(0.0)
    return {
        "charge_kwh": float(batt.clip(lower=0.0).sum()),
        "discharge_kwh": float((-batt.clip(upper=0.0)).sum()),
    }


def _wall_s(run_dir: Path) -> float | None:
    path = run_dir / "wall_time.json"
    if not path.is_file():
        return None
    raw = _load(path).get("wall_s")
    return None if raw is None else float(raw)


def discover_k_runs(run_root: Path, commit_hours: list[int]) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for k in commit_hours:
        candidate = run_root / f"k{k}"
        if (candidate / "backtesting_log.json").is_file():
            found[k] = candidate
    return found


def build_rows(
    runs: dict[int, dict],
    run_dirs: dict[int, Path],
    *,
    baseline_k: int,
) -> list[dict]:
    if baseline_k not in runs:
        raise SystemExit(f"Baseline commit_hours={baseline_k} missing among runs.")
    base = runs[baseline_k]
    labels = base.get("labels", {})
    ref_id = base.get("reference_id", "historical_reference")
    base_totals = base["summary"]["total_eur"]
    ks = sorted(runs)
    rows: list[dict] = []
    for sid, label in labels.items():
        if sid == ref_id:
            continue
        row: dict = {
            "scenario_id": sid,
            "label": label,
            "ref_eur": base_totals.get(ref_id),
        }
        for k in ks:
            payload = runs[k]
            totals = payload["summary"]["total_eur"]
            eur = totals.get(sid)
            row[f"eur_k{k}"] = eur
            if eur is not None and baseline_k in totals and totals.get(sid) is not None:
                row[f"d_eur_k{k}_vs_k{baseline_k}"] = round(
                    float(eur) - float(base_totals.get(sid) or 0.0), 4
                )
            else:
                row[f"d_eur_k{k}_vs_k{baseline_k}"] = None
            plaus = payload.get("plausibility", {})
            row[f"plaus_k{k}"] = _plaus_ok(plaus, sid)
            hourly = run_dirs[k] / "backtesting_hourly.csv"
            batt = _battery_totals(hourly, sid)
            row[f"batt_charge_kwh_k{k}"] = round(batt["charge_kwh"], 2)
            row[f"batt_discharge_kwh_k{k}"] = round(batt["discharge_kwh"], 2)
        rows.append(row)
    return rows


def build_markdown(
    *,
    run_root: Path,
    runs: dict[int, dict],
    run_dirs: dict[int, Path],
    rows: list[dict],
    baseline_k: int,
) -> str:
    ks = sorted(runs)
    base = runs[baseline_k]
    period = base.get("period", {})
    labels = base.get("labels", {})
    ref_id = base.get("reference_id", "historical_reference")
    ref_eur = base["summary"]["total_eur"].get(ref_id)

    if ref_eur is not None:
        ref_line = f"- Reference ({labels.get(ref_id, ref_id)}): {ref_eur:.2f} €"
    else:
        ref_line = f"- Reference: {ref_id}"
    lines = [
        "# commit_hours Backtesting Comparison",
        "",
        f"- Run root: `{run_root.as_posix()}`",
        f"- Period: `{period.get('start')}` – `{period.get('end')}` "
        f"· windows={period.get('windows')} · horizon=`{period.get('horizon_mode')}`",
        f"- Baseline K: **{baseline_k}**",
        ref_line,
        "",
        "## Wall time (full backtesting process)",
        "",
        "| commit_hours | wall_s | speedup vs K=" + str(baseline_k) + " |",
        "|--------------|--------|------------------|",
    ]
    base_wall = _wall_s(run_dirs[baseline_k])
    for k in ks:
        wall = _wall_s(run_dirs[k])
        if wall is None:
            speed = "—"
            wall_s = "—"
        else:
            wall_s = f"{wall:.1f}"
            if base_wall and wall > 0:
                speed = f"{base_wall / wall:.2f}x"
            else:
                speed = "—"
        lines.append(f"| {k} | {wall_s} | {speed} |")

    eur_cols = " | ".join(f"€ K={k}" for k in ks)
    d_cols = " | ".join(f"Δ€ vs K={baseline_k} (K={k})" for k in ks if k != baseline_k)
    header = f"| Scenario | {eur_cols} |"
    if d_cols:
        header = f"| Scenario | {eur_cols} | {d_cols} |"
    sep = "|" + "|".join(["----------"] * (header.count("|") - 1)) + "|"
    lines.extend(["", "## Costs by scenario", "", header, sep])

    for row in rows:
        cells = [str(row["label"])]
        for k in ks:
            val = row.get(f"eur_k{k}")
            cells.append(f"{val:.2f}" if val is not None else "—")
        for k in ks:
            if k == baseline_k:
                continue
            dval = row.get(f"d_eur_k{k}_vs_k{baseline_k}")
            cells.append(f"{dval:+.3f}" if dval is not None else "—")
        lines.append("| " + " | ".join(cells) + " |")

    plaus_cols = " | ".join(f"plaus K={k}" for k in ks)
    lines.extend(
        [
            "",
            "## Plausibility (ok/total windows)",
            "",
            f"| Scenario | {plaus_cols} |",
            "|" + "|".join(["----------"] * (len(ks) + 1)) + "|",
        ]
    )
    for row in rows:
        cells = [str(row["label"])] + [str(row.get(f"plaus_k{k}", "—")) for k in ks]
        lines.append("| " + " | ".join(cells) + " |")

    batt_hdr = " | ".join(
        f"chg/dis K={k}" for k in ks
    )
    lines.extend(
        [
            "",
            "## Battery energy (sum batt_action_kw, kWh)",
            "",
            f"| Scenario | {batt_hdr} |",
            "|" + "|".join(["----------"] * (len(ks) + 1)) + "|",
        ]
    )
    for row in rows:
        cells = [str(row["label"])]
        for k in ks:
            chg = row.get(f"batt_charge_kwh_k{k}", 0.0)
            dis = row.get(f"batt_discharge_kwh_k{k}", 0.0)
            cells.append(f"{chg:.1f}/{dis:.1f}")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def compare_run_root(
    run_root: Path,
    *,
    commit_hours: list[int],
    baseline_k: int,
    markdown_out: Path,
    csv_out: Path | None,
) -> list[dict]:
    run_dirs = discover_k_runs(run_root, commit_hours)
    if len(run_dirs) < 2:
        raise SystemExit(
            f"Need at least two k*/backtesting_log.json under {run_root} "
            f"(found: {sorted(run_dirs)})."
        )
    runs = {k: _load(d / "backtesting_log.json") for k, d in run_dirs.items()}
    rows = build_rows(runs, run_dirs, baseline_k=baseline_k)
    md = build_markdown(
        run_root=run_root,
        runs=runs,
        run_dirs=run_dirs,
        rows=rows,
        baseline_k=baseline_k,
    )
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(md, encoding="utf-8")
    if csv_out is not None:
        write_csv(csv_out, rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare commit_hours backtesting run directories (k1/k6/k24)."
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        required=True,
        help="Directory containing k1/, k6/, k24/ (each with backtesting_log.json).",
    )
    parser.add_argument(
        "--commit-hours",
        type=str,
        default="1,6,24",
        help="Comma-separated K values to compare (default: 1,6,24).",
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=1,
        help="Baseline commit_hours for deltas/speedup (default: 1).",
    )
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional CSV path (default: sibling of -o with .csv).",
    )
    args = parser.parse_args(argv)
    hours = [int(p.strip()) for p in args.commit_hours.split(",") if p.strip()]
    csv_path = args.csv or args.output.with_suffix(".csv")
    compare_run_root(
        args.run_root,
        commit_hours=hours,
        baseline_k=args.baseline,
        markdown_out=args.output,
        csv_out=csv_path,
    )
    print(f"Comparison written: {args.output}")
    print(f"CSV written: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
