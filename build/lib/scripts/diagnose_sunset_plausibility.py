"""Schritt 2a–2c: Sunset-Plausibilität aufschlüsseln und mit fixed_24h vergleichen."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from data.data_loader import load_market_prices
from scripts.run_backtesting import resolve_backtesting_window
from simulation.backtesting_horizon import (
    compute_sunrise_planning_at_anchor,
    effective_sunrise_soc_min_index,
)
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    _simulate_anchor_step,
    build_historical_matrix_for_slots,
    validate_window_consumption,
    window_slot_datetimes,
)
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW

SUNSET_LOG = ROOT / "backtesting_logs" / "horizon_compare_2025_full_sunset_window.json"
OUT_2A = ROOT / "backtesting_logs" / "plausibility_sunset_2025.json"
OUT_2BC = ROOT / "backtesting_logs" / "plausibility_sunset_compare_2bc.json"

SAMPLE_WINDOWS = (
    "2025-01-10T07:00:00",
    "2025-12-08T07:00:00",
    "2025-10-15T07:00:00",
)
OCT_WINDOWS = ("2025-10-15T07:00:00", "2025-10-16T07:00:00")


def _parse_anchor(value: str) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


def _load_sunset_failures(scenario_id: str) -> list[dict]:
    meta = json.loads(SUNSET_LOG.read_text(encoding="utf-8"))
    return list(meta.get("plausibility", {}).get(scenario_id, {}).get("failures", []))


def _summarize_failures(failures: list[dict]) -> dict:
    by_month: Counter[str] = Counter()
    by_anchor_hour: Counter[str] = Counter()
    marginal = 0
    baseload_dominated = 0
    for item in failures:
        end = _parse_anchor(item["window_end"])
        by_month[end.strftime("%Y-%m")] += 1
        by_anchor_hour[f"{end.hour:02d}:00"] += 1
        diff = float(item["diff_kwh"])
        flex_d = abs(float(item.get("flex_diff_kwh", 0.0)))
        baseload_d = abs(float(item.get("baseload_diff_kwh", 0.0)))
        if diff <= 0.65:
            marginal += 1
        if flex_d < 0.02 and baseload_d >= diff * 0.9:
            baseload_dominated += 1
    return {
        "total_failures": len(failures),
        "by_month": dict(sorted(by_month.items())),
        "by_anchor_hour": dict(sorted(by_anchor_hour.items())),
        "marginal_count_diff_le_0_65_kwh": marginal,
        "baseload_dominated_count": baseload_dominated,
    }


def _hourly_baseload_rows(chart_rows: list[dict]) -> list[dict]:
    rows = []
    for row in chart_rows:
        slot = row.get("slot_datetime")
        if hasattr(slot, "isoformat"):
            slot_str = slot.isoformat()
        else:
            slot_str = str(slot)
        baseload = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        rows.append({"slot": slot_str, "baseload_kw": round(baseload, 3)})
    return rows


def _setup_cache_prices_scenario():
    sim_cfg = config.get_file_paths_battery_simulation()
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, 1, 1),
        pd.Timestamp(2026, 1, 1),
        sim_cfg.get("price_range", "last_12_months"),
        sim_cfg["path_consumption"],
        sim_cfg["path_production"],
    )
    cache = HistoricalDataCache()
    cache.load()
    prices_df = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )
    scenario = config.get_backtesting_scenarios()["battery_10kwh_dynamic"]
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario)
    battery_params = _scenario_to_battery_params(scenario)
    return cache, prices_df, scenario, feed_in, battery_params


def _simulate_mode(
    anchor: datetime,
    *,
    horizon_mode: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario: dict,
    feed_in,
    battery_params: dict,
    initial_soc: float = 50.0,
) -> tuple[list[dict], dict, object]:
    chart_rows, _matrix, meta, _soc = _simulate_anchor_step(
        anchor,
        initial_soc,
        horizon_mode=horizon_mode,
        cache=cache,
        prices_df=prices_df,
        scenario_params=scenario,
        battery_params=battery_params,
        feed_in_settings=feed_in,
        hours_done=0,
        collect_cbc=False,
    )
    plaus = validate_window_consumption(chart_rows, meta)
    return chart_rows, meta, plaus


def _compare_window(
    window_end: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario: dict,
    feed_in,
    battery_params: dict,
) -> dict:
    anchor = _parse_anchor(window_end)
    slots = window_slot_datetimes(anchor)
    _, meta_slots = build_historical_matrix_for_slots(
        slots, cache, prices_df, window_end=anchor, feed_in_settings=feed_in
    )
    baseload_stored, hist_totals, total_load, hourly_flex = cache.get_window_consumption(
        slots
    )

    fixed_rows, fixed_meta, fixed_plaus = _simulate_mode(
        anchor,
        horizon_mode=FIXED_24H,
        cache=cache,
        prices_df=prices_df,
        scenario=scenario,
        feed_in=feed_in,
        battery_params=battery_params,
    )
    sunset_rows, sunset_meta, sunset_plaus = _simulate_mode(
        anchor,
        horizon_mode=SUNRISE_WINDOW,
        cache=cache,
        prices_df=prices_df,
        scenario=scenario,
        feed_in=feed_in,
        battery_params=battery_params,
    )

    _, sunrise_index = compute_sunrise_planning_at_anchor(anchor, scenario)
    sunrise_effective = effective_sunrise_soc_min_index(sunrise_index)

    hourly = []
    for index, slot in enumerate(slots):
        fixed_kw = float(fixed_rows[index].get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        sunset_kw = float(
            sunset_rows[index].get("Verbrauch-Prognose (kW)", 0.0) or 0.0
        )
        hourly.append(
            {
                "slot": slot.isoformat(),
                "csv_baseload_kw": round(float(baseload_stored[index]), 3),
                "csv_total_kw": round(float(total_load[index]), 3),
                "csv_flex_kw": round(float(hourly_flex[index]), 3),
                "fixed_baseload_kw": round(fixed_kw, 3),
                "sunset_baseload_kw": round(sunset_kw, 3),
                "fixed_vs_sunset_delta_kw": round(fixed_kw - sunset_kw, 3),
            }
        )

    return {
        "window_end": window_end,
        "sunrise_index": sunrise_index,
        "sunrise_soc_min_effective": sunrise_effective,
        "csv_meta": {
            "historical_total_kwh": meta_slots["historical_total_kwh"],
            "baseload_kwh_derived": meta_slots["baseload_kwh"],
            "baseload_stored_kwh": meta_slots["baseload_stored_kwh"],
            "baseload_adjustment_kwh": meta_slots["baseload_adjustment_kwh"],
            "historical_totals": hist_totals,
        },
        "fixed_plausibility": {
            "ok": fixed_plaus.ok,
            "diff_kwh": fixed_plaus.diff_kwh,
            "baseload_diff_kwh": fixed_plaus.baseload_diff_kwh,
            "flex_diff_kwh": fixed_plaus.flex_diff_kwh,
        },
        "sunset_plausibility": {
            "ok": sunset_plaus.ok,
            "diff_kwh": sunset_plaus.diff_kwh,
            "baseload_diff_kwh": sunset_plaus.baseload_diff_kwh,
            "flex_diff_kwh": sunset_plaus.flex_diff_kwh,
        },
        "hourly": hourly,
    }


def _investigate_oct_window(
    window_end: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    feed_in,
) -> dict:
    anchor = _parse_anchor(window_end)
    slots = window_slot_datetimes(anchor)
    baseload_stored, hist_totals, total_load, hourly_flex = cache.get_window_consumption(
        slots
    )
    _, meta = build_historical_matrix_for_slots(
        slots, cache, prices_df, window_end=anchor, feed_in_settings=feed_in
    )
    hourly = []
    for index, slot in enumerate(slots):
        flex_sum = float(hourly_flex[index])
        total = float(total_load[index])
        stored = float(baseload_stored[index])
        derived = round(max(0.0, total - flex_sum), 3)
        hourly.append(
            {
                "slot": slot.isoformat(),
                "csv_baseload_kw": round(stored, 3),
                "csv_total_kw": round(total, 3),
                "csv_flex_kw": round(flex_sum, 3),
                "derived_baseload_kw": derived,
                "flex_exceeds_total": flex_sum > total + 0.001,
            }
        )
    flex_exceed_hours = sum(1 for row in hourly if row["flex_exceeds_total"])
    return {
        "window_end": window_end,
        "meta": {
            "historical_total_kwh": meta["historical_total_kwh"],
            "baseload_kwh_derived": meta["baseload_kwh"],
            "baseload_stored_kwh": meta["baseload_stored_kwh"],
            "baseload_adjustment_kwh": meta["baseload_adjustment_kwh"],
            "historical_totals": hist_totals,
        },
        "flex_exceeds_total_hours": flex_exceed_hours,
        "hourly": hourly,
    }


def run_step_2a(scenario_id: str = "battery_10kwh_dynamic") -> dict:
    failures = _load_sunset_failures(scenario_id)
    winter = [
        f for f in failures if _parse_anchor(f["window_end"]).month in (12, 1, 2, 3)
    ]
    payload = {
        "source_log": str(SUNSET_LOG),
        "scenario_id": scenario_id,
        "summary": _summarize_failures(failures),
        "winter_failures_dec_mar": winter,
        "all_failures": failures,
    }
    OUT_2A.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def run_step_2bc() -> dict:
    cache, prices_df, scenario, feed_in, battery_params = _setup_cache_prices_scenario()
    comparisons = [
        _compare_window(
            window,
            cache,
            prices_df,
            scenario,
            feed_in,
            battery_params,
        )
        for window in SAMPLE_WINDOWS
    ]
    oct_investigation = [
        _investigate_oct_window(window, cache, prices_df, feed_in)
        for window in OCT_WINDOWS
    ]
    payload = {
        "sample_comparisons_fixed_vs_sunset": comparisons,
        "oct_15_16_investigation": oct_investigation,
    }
    OUT_2BC.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _print_report(payload_2a: dict, payload_2bc: dict) -> None:
    summary = payload_2a["summary"]
    print("\n=== Schritt 2a: Sunset-Plausibilität ===")
    print(f"Fehler gesamt: {summary['total_failures']}")
    print(f"Nach Monat: {summary['by_month']}")
    print(f"Nach Anker-Uhrzeit: {summary['by_anchor_hour']}")
    print(
        f"Knapp ueber Toleranz (diff<=0.65 kWh): {summary['marginal_count_diff_le_0_65_kwh']}"
    )
    print(f"Grundlast-dominiert: {summary['baseload_dominated_count']}")
    print(f"JSON: {OUT_2A}")

    print("\n=== Schritt 2b: fixed vs sunset (Stichproben) ===")
    for item in payload_2bc["sample_comparisons_fixed_vs_sunset"]:
        print(f"\n--- {item['window_end']} ---")
        print(
            f"  Sunrise-Index: {item['sunrise_index']}, "
            f"SOC-Anker aktiv: {item['sunrise_soc_min_effective']}"
        )
        fp = item["fixed_plausibility"]
        sp = item["sunset_plausibility"]
        print(
            f"  fixed:   ok={fp['ok']} Δ={fp['diff_kwh']:.3f} "
            f"(Grundlast {fp['baseload_diff_kwh']:.3f}, Flex {fp['flex_diff_kwh']:.3f})"
        )
        print(
            f"  sunset:  ok={sp['ok']} Δ={sp['diff_kwh']:.3f} "
            f"(Grundlast {sp['baseload_diff_kwh']:.3f}, Flex {sp['flex_diff_kwh']:.3f})"
        )
        deltas = [abs(h["fixed_vs_sunset_delta_kw"]) for h in item["hourly"]]
        print(
            f"  Stündlich fixed≠sunset: max |Δ|={max(deltas):.3f} kW, "
            f"Summe |Δ|={sum(deltas):.3f} kWh"
        )

    print("\n=== Schritt 2c: Okt 15/16 CSV-Daten ===")
    for item in payload_2bc["oct_15_16_investigation"]:
        meta = item["meta"]
        print(f"\n--- {item['window_end']} ---")
        print(
            f"  Total={meta['historical_total_kwh']:.2f} kWh, "
            f"Grundlast derived={meta['baseload_kwh_derived']:.2f}, "
            f"stored={meta['baseload_stored_kwh']:.2f}, "
            f"adjustment={meta['baseload_adjustment_kwh']:.2f}"
        )
        print(f"  Flex-Summen: {meta['historical_totals']}")
        print(f"  Stunden Flex>Total: {item['flex_exceeds_total_hours']}/24")
    print(f"\nJSON: {OUT_2BC}")


def main() -> None:
    payload_2a = run_step_2a()
    payload_2bc = run_step_2bc()
    _print_report(payload_2a, payload_2bc)


if __name__ == "__main__":
    main()
