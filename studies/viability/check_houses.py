"""Check finished house runs of stage 0 and print one Markdown report (study plan § 5.0).

Reads ``<packs>/<id>/house.json`` and ``results/<run>/`` (SE log, series, ladder CSVs). Hard
checks print ``FEHLER``; values to judge by eye print ``AUFFAELLIG`` with the threshold.

  python -m studies.viability.check_houses --packs studies/viability/packs_s0 --run year
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from simulation.backtesting_log import load_backtesting_log
from studies.viability.appliances import baseload_target_kwh

STUDY_DIR = Path(__file__).resolve().parent
ENERGY_BALANCE_TOLERANCE_KWH = 1.0
RULE_MODEL_TOLERANCE = 0.25
PV_YIELD_RANGE_KWH_PER_KWP = (950.0, 1450.0)
LADDER_SLACK_EUR = 0.5
SLOT_H = 0.25


def _series(hourly: pd.DataFrame, result_id: str) -> pd.DataFrame:
    return hourly.loc[hourly["scenario_id"] == result_id]


def energy_balance_gap_kwh(part: pd.DataFrame, pv_kwh: float) -> float:
    """Import − export − (load − PV) of a step without a battery; 0 unless energy leaks.

    Reference series carry no PV column values, so the PV comes from the optimized run.
    """
    grid = part["import_kwh"].sum() - part["export_kwh"].sum()
    return float(grid - (part["consumption_kw"].sum() * SLOT_H - pv_kwh))


def _ev_charging_outside_window(part: pd.DataFrame, column: str, windows: dict) -> float:
    """kWh charged outside the pattern's window."""
    index = pd.DatetimeIndex(part["ts"])
    hours, weekend = index.hour, index.dayofweek >= 5
    energy = 0.0
    for key, mask in (("werktag", ~weekend), ("wochenende", weekend)):
        start, end = windows[key]
        allowed = (hours >= start) | (hours < end) if start > end else (hours >= start) & (hours < end)
        energy += float(part.loc[mask & ~allowed, column].sum()) * SLOT_H
    return energy


def check_house(root: Path, run: str, params: dict) -> tuple[list[str], list[dict]]:
    """Findings of one house and one row per scenario."""
    record = json.loads((root / "house.json").read_text(encoding="utf-8"))
    derived, earnie = record["derived"], record["earnie"]
    run_dir = root / "results" / run
    meta, hourly = load_backtesting_log(str(run_dir))
    summary = pd.read_csv(run_dir / "reference_ladder_summary.csv", sep=";", decimal=",")
    findings: list[str] = []

    model_wp = earnie["consumers"].get("wp_heating", 0.0)
    rule_wp = derived["heat_pump_kwh"]
    if rule_wp and abs(model_wp - rule_wp) / rule_wp > RULE_MODEL_TOLERANCE:
        findings.append(f"AUFFAELLIG WP-Strom: Modell {model_wp:.0f} kWh, Regel {rule_wp:.0f} kWh")
    profile_rows = json.loads((root / "pack" / "config" / "house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]["consumers"]
    baseload_target = baseload_target_kwh(derived["household_kwh"], profile_rows)
    if abs(earnie["baseload_kwh"] - baseload_target) > 5.0:
        findings.append(f"FEHLER Grundlast {earnie['baseload_kwh']:.0f} kWh, Regel {baseload_target:.0f} kWh")

    fuel_blocks = meta.get("heat_fuel") or {}
    rows: list[dict] = []
    for item in summary.itertuples():
        sid = item.scenario_id
        ladder = meta["ladder_by_scenario"][sid]
        ids = {"L0": meta["reference_by_scenario"][sid], "L1": ladder["l1"], "L2": ladder["l2"], "L3": sid}
        booked = meta["booked_consumption"]
        l3 = _series(hourly, sid)
        pv_kwh = float(l3["pv_kw"].sum()) * SLOT_H
        for step, result_id in ids.items():
            part = _series(hourly, result_id)
            gap = energy_balance_gap_kwh(part, pv_kwh) if step == "L0" else None
            if gap is not None and abs(gap) > ENERGY_BALANCE_TOLERANCE_KWH:
                findings.append(f"FEHLER {sid} {step}: Energiebilanz weicht um {gap:.1f} kWh ab")
            duplicates = booked.get(result_id, {}).get("duplicate_slots", 0)
            gaps = booked.get(result_id, {}).get("gap_slots", 0)
            if duplicates or gaps:
                findings.append(f"FEHLER {sid} {step}: {duplicates} doppelte, {gaps} fehlende Slots")

        curtailed_kwh = pv_kwh - (
            l3["consumption_kw"].sum() * SLOT_H - l3["import_kwh"].sum() + l3["export_kwh"].sum()
        )
        yield_kwp = pv_kwh / derived["pv_kwp"] if derived["pv_kwp"] else 0.0
        low, high = PV_YIELD_RANGE_KWH_PER_KWP
        full_year = meta["period"]["start"].endswith("-01-01") and meta["period"]["end"].endswith("-12-31")
        if full_year and not low <= yield_kwp <= high:
            findings.append(f"AUFFAELLIG {sid}: PV-Ertrag {yield_kwp:.0f} kWh/kWp ausserhalb {low:.0f}–{high:.0f}")

        order = [("L0", item.l0_eur), ("L1", item.l1_eur + item.l1_soc_correction_eur),
                 ("L2", item.l2_eur + item.l2_soc_correction_eur), ("L3", item.l3_eur)]
        fuels = {step: float((fuel_blocks.get(ids[step]) or {}).get("fuel_eur") or 0.0) for step in ids}
        with_fuel = {step: value + fuels[step] for step, value in order}
        steps = list(with_fuel.items())
        for (upper, upper_cost), (lower, lower_cost) in zip(steps, steps[1:]):
            if lower_cost > upper_cost + LADDER_SLACK_EUR:
                findings.append(
                    f"AUFFAELLIG {sid}: {lower} ({lower_cost:.2f} €) teurer als {upper} ({upper_cost:.2f} €)"
                )
        for step in ("L1", "L2"):
            failed = getattr(item, f"plausibility_failed_windows_{step.lower()}")
            if failed:
                findings.append(f"FEHLER {sid} {step}: {failed} Fenster mit abweichender Energie")
        block = (meta.get("plausibility") or {}).get(sid) or {}
        if block.get("failed_count"):
            findings.append(f"FEHLER {sid} L3: {block['failed_count']} Fenster mit abweichender Energie")
        for step in ids:
            report = (meta.get("ladder_report") or {}).get(ids[step]) or {}
            for key in ("no_shape_windows", "no_published_block_windows"):
                if report.get(key):
                    findings.append(f"AUFFAELLIG {sid} {step}: {key} {report[key]}")

        for index, pattern in enumerate(derived["ev_patterns"], start=1):
            column = f"ev{index}_kw"
            windows = params["eauto_muster"][pattern]
            for step in ("L2", "L3"):
                part = _series(hourly, ids[step])
                if column not in part or part[column].isna().all():
                    findings.append(f"FEHLER {sid} {step}: Spalte {column} fehlt")
                    continue
                outside = _ev_charging_outside_window(part, column, windows)
                if outside > 0.5:
                    findings.append(f"FEHLER {sid} {step}: {column} laedt {outside:.1f} kWh ausserhalb des Fensters")

        rod = {step: float((fuel_blocks.get(ids[step]) or {}).get("rod_kwh") or 0.0) for step in ids}
        fuel_kwh = {step: float((fuel_blocks.get(ids[step]) or {}).get("fuel_kwh") or 0.0) for step in ids}
        rows.append({
            "Haus": derived["id"],
            "Szenario": sid,
            "L0": item.l0_eur,
            "L1": item.l1_eur,
            "L2": item.l2_eur,
            "L3": item.l3_eur,
            "Brennstoff L0/L1/L2/L3 €": "/".join(f"{fuels[s]:.0f}" for s in ids),
            "Brennstoff L0/L3 kWh": f"{fuel_kwh['L0']:.0f}/{fuel_kwh['L3']:.0f}",
            "Heizstab L3 kWh": round(rod["L3"]),
            "L2−L3 mit Brennstoff": with_fuel["L2"] - with_fuel["L3"],
            "Regel-Anteil": item.rule_share,
            "kWh/kWp": round(yield_kwp),
            "Verbrauch L3 kWh": round(meta["booked_consumption"][sid]["consumption_kwh"]),
            "Import L3 kWh": round(float(l3["import_kwh"].sum())),
            "Export L3 kWh": round(float(l3["export_kwh"].sum())),
            "Abgeregelt L3 kWh": round(float(curtailed_kwh)),
        })
    return findings, rows


def main() -> None:
    from studies.viability import params as params_mod

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs", type=Path, default=STUDY_DIR / "packs")
    parser.add_argument("--run", default="year")
    parser.add_argument("--ids", help="Kommagetrennt; Standard: alle Pakete mit diesem Lauf")
    args = parser.parse_args()
    params = params_mod.load()
    ids = args.ids.split(",") if args.ids else sorted(
        p.name for p in args.packs.iterdir() if (p / "results" / args.run / "reference_ladder_summary.csv").is_file()
    )
    all_rows: list[dict] = []
    print(f"# Stichproben, Lauf {args.run}\n")
    for house_id in ids:
        findings, rows = check_house(args.packs / house_id, args.run, params)
        all_rows.extend(rows)
        print(f"## {house_id}\n")
        print("\n".join(f"- {finding}" for finding in findings) or "- keine Befunde")
        print()
    frame = pd.DataFrame(all_rows)
    print("## Tabelle\n")
    print("| " + " | ".join(frame.columns) + " |")
    print("|" + "---|" * len(frame.columns))
    for row in frame.round(2).itertuples(index=False):
        print("| " + " | ".join(str(value) for value in row) + " |")


if __name__ == "__main__":
    main()
