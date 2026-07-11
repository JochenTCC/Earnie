#!/usr/bin/env python3
"""
generate_cons_data.py – Erzeugt cons_data_hourly.csv aus Loxone-Logs oder config.json.

Einmaliger Migrations-Job; laufende Pflege erfolgt über main.py (cons_data_store).

Aufruf: python -m scripts.generate_cons_data
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta, time
from typing import Iterable

import pandas as pd

from runtime_store.config_load import load_config_or_exit

config = load_config_or_exit()
from data import cons_data_store
from data.cons_data_house_profile import (
    build_synthetic_dataframe_from_house_profile,
    resolve_runtime_house_profile,
)
from integrations import loxone_log_import

SOURCE_LOXONE = cons_data_store.SOURCE_LOXONE
SOURCE_SYNTHETIC = cons_data_store.SOURCE_SYNTHETIC

# Nur für Offline-Synthese ohne Loxone (kein Merker Batteriekapazität_E-Auto).
_SYNTHETIC_EAUTO_BATTERY_KWH = 77.0

get_output_path = cons_data_store.get_output_path
load_cons_data = cons_data_store.load_cons_data
save_cons_data = cons_data_store.save_cons_data
append_measured_hours = cons_data_store.append_measured_hours
build_hour_row_from_measurements = cons_data_store.build_hour_row_from_measurements


def build_from_loxone() -> pd.DataFrame | None:
    """Liest Loxone-CSVs und liefert stündliche Mittelwerte im generischen Format."""
    path_total = config.get("PATH_CONSUMPTION_TOTAL", cast=str)
    if not path_total or not os.path.exists(path_total):
        print(f"[WARN] Kein Gesamtverbrauchs-Log gefunden: {path_total!r}")
        return None

    s_total = loxone_log_import.load_and_resample_csv(path_total)
    if s_total.empty:
        print("[WARN] Gesamtverbrauchs-Zeitreihe ist leer.")
        return None

    df = loxone_log_import.build_flexible_consumer_dataframe(s_total)
    df = loxone_log_import.compute_baseload(df)

    out = pd.DataFrame(index=df.index)
    out["total_kw"] = df["Total"].round(3)
    out["baseload_kw"] = df["BaseLoad"].round(3)
    for consumer in config.get_flexible_consumers():
        out[f"{consumer['id']}_kw"] = df[consumer["name"]].round(3)

    path_prod = config.get("PATH_PRODUCTION", cast=str)
    if path_prod and os.path.exists(path_prod):
        s_pv = loxone_log_import.load_and_resample_csv(path_prod)
        out["pv_kw"] = s_pv.reindex(out.index, fill_value=0.0).round(3)
    else:
        out["pv_kw"] = 0.0

    out["source"] = SOURCE_LOXONE
    print(
        f"[OK] Loxone-Daten geladen: {out.index.min()} -> {out.index.max()} "
        f"({len(out)} Stunden)"
    )
    return cons_data_store._normalize_cons_dataframe(out)


def _synthetic_baseload_kw(hour: int, weekday: int, month: int) -> float:
    winter_boost = 0.12 if month in (11, 12, 1, 2) else 0.0
    weekend = 0.08 if weekday >= 5 else 0.0
    if hour <= 5:
        base = 0.32
    elif hour <= 8:
        base = 0.55
    elif hour <= 17:
        base = 0.48
    elif hour <= 21:
        base = 0.72
    else:
        base = 0.40
    return round(base + winter_boost + weekend, 3)


def _distribute_daily_kwh(
    daily_kwh: float,
    hours: Iterable[int],
    nominal_kw: float,
) -> dict[int, float]:
    hour_list = list(hours)
    if not hour_list or daily_kwh <= 0:
        return {h: 0.0 for h in range(24)}
    per_hour = min(nominal_kw, daily_kwh / len(hour_list))
    return {h: (per_hour if h in hour_list else 0.0) for h in range(24)}


def _synthetic_flex_profile(consumer: dict, day: date) -> dict[int, float]:
    cid = consumer["id"]
    nominal = float(consumer.get("nominal_power_kw", 1.0))
    weekday = day.weekday()

    if consumer.get("signal_type") == "binary":
        daily_kwh = float(consumer.get("daily_target_kwh", nominal * 2))
        if day.month in (11, 12, 1, 2, 3):
            active = list(range(5, 9)) + list(range(17, 22))
        else:
            active = list(range(6, 8)) + list(range(19, 23))
        return _distribute_daily_kwh(daily_kwh, active, nominal)

    sched = consumer.get("charging_schedule") or {}
    if sched.get("enabled"):
        day_cfg = sched.get("weekend" if weekday >= 5 else "weekday") or {}
        from_h = int(day_cfg.get("car_available_from_hour", 19))
        ready_h = int(day_cfg.get("ready_by_hour", 7))
        rest_soc = day_cfg.get("daily_rest_soc", 30)
        daily_kwh = (
            config.Config.target_kwh_from_rest_soc(
                consumer, rest_soc, capacity_kwh=_SYNTHETIC_EAUTO_BATTERY_KWH
            )
            or 0.0
        )
        if from_h <= ready_h:
            charge_hours = list(range(from_h, ready_h))
        else:
            charge_hours = list(range(from_h, 24)) + list(range(0, ready_h))
        return _distribute_daily_kwh(daily_kwh, charge_hours, nominal)

    daily_kwh = float(consumer.get("daily_target_kwh", nominal * 2))
    active = (
        list(range(10, 14)) + list(range(18, 22))
        if cid == "swimspa"
        else list(range(8, 20))
    )
    return _distribute_daily_kwh(daily_kwh, active, nominal)


def _synthetic_pv_kw(hour: int, month: int, kwp: float) -> float:
    if month in (11, 12, 1):
        peak = kwp * 0.12
    elif month in (2, 3, 10):
        peak = kwp * 0.38
    elif month in (4, 9):
        peak = kwp * 0.55
    else:
        peak = kwp * 0.72
    if hour < 6 or hour > 20:
        return 0.0
    x = (hour - 13) / 5.0
    return round(max(0.0, peak * (1.0 - x * x)), 3)


def build_synthetic(
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    today = datetime.now().date()
    if end is None:
        end = today - timedelta(days=1)
    if start is None:
        retention = cons_data_store.get_retention_months()
        days = max(365, retention * 31) if retention > 0 else 395
        start = end - timedelta(days=days)

    kwp = float(config.get("PV_KWP", cast=float) or 6.0)
    house_profile = resolve_runtime_house_profile()
    if house_profile and house_profile.get("consumers"):
        df = build_synthetic_dataframe_from_house_profile(
            house_profile,
            start=start,
            end=end,
            kwp=kwp,
            source=SOURCE_SYNTHETIC,
            pv_kw_for_hour=_synthetic_pv_kw,
        )
        df = cons_data_store._normalize_cons_dataframe(df)
        consumer_ids = [
            col[: -len("_kw")]
            for col in df.columns
            if str(col).endswith("_kw")
            and str(col[: -len("_kw")]) not in {"total", "baseload", "pv"}
        ]
        print(
            f"[OK] Synthetische Daten aus Hausprofil '{house_profile.get('id')}' erzeugt: "
            f"{df.index.min()} -> {df.index.max()} ({len(df)} Stunden, "
            f"{len(consumer_ids)} Verbraucher)"
        )
        return df

    consumers = config.get_flexible_consumers()
    consumer_ids = [c["id"] for c in consumers]
    rows: list[dict] = []

    current = start
    while current <= end:
        baseload = {
            h: _synthetic_baseload_kw(h, current.weekday(), current.month)
            for h in range(24)
        }
        flex_by_hour: dict[int, dict[str, float]] = {h: {} for h in range(24)}
        for consumer in consumers:
            profile = _synthetic_flex_profile(consumer, current)
            for h, kw in profile.items():
                flex_by_hour[h][consumer["id"]] = kw

        for hour in range(24):
            ts = datetime.combine(current, time(hour=hour))
            flex_vals = flex_by_hour[hour]
            flex_sum = sum(flex_vals.values())
            base = baseload[hour]
            rows.append(
                {
                    "timestamp": ts,
                    "total_kw": round(base + flex_sum, 3),
                    "baseload_kw": base,
                    "pv_kw": _synthetic_pv_kw(hour, current.month, kwp),
                    "source": SOURCE_SYNTHETIC,
                    **{f"{cid}_kw": round(flex_vals.get(cid, 0.0), 3) for cid in consumer_ids},
                }
            )
        current += timedelta(days=1)

    df = pd.DataFrame(rows).set_index("timestamp")
    print(
        f"[OK] Synthetische Daten erzeugt: {df.index.min()} -> {df.index.max()} "
        f"({len(df)} Stunden)"
    )
    return cons_data_store._normalize_cons_dataframe(df)


def generate(
    source: str = "auto",
    output: str | None = None,
    synthetic_start: date | None = None,
    synthetic_end: date | None = None,
) -> pd.DataFrame:
    output = output or get_output_path()

    if source == "auto":
        df = build_from_loxone()
        if df is None or df.empty:
            print("[INFO] Fallback auf synthetische Daten aus config.json ...")
            df = build_synthetic(synthetic_start, synthetic_end)
    elif source == "loxone":
        df = build_from_loxone()
        if df is None or df.empty:
            raise SystemExit("Abbruch: Keine Loxone-Daten verfügbar.")
    elif source == "synthetic":
        df = build_synthetic(synthetic_start, synthetic_end)
    else:
        raise SystemExit(f"Unbekannte Quelle: {source}")

    save_cons_data(df, output)
    return df


def print_stats(path: str | None = None) -> None:
    path = path or get_output_path()
    df = load_cons_data(path)
    if df.empty:
        print(f"Keine Daten in {path}")
        return
    print(f"\n[STATS] {path}")
    print(f"  Zeitraum: {df.index.min()} -> {df.index.max()}")
    print(f"  Stunden:  {len(df)}")
    print(f"  Quellen:  {df['source'].value_counts().to_dict()}")
    print(f"  Total kWh (Summe Stundenmittel): {df['total_kw'].sum():.1f}")
    print(f"  PV kWh:   {df['pv_kw'].sum():.1f}")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generische Stunden-Log-Datei für den Energy Optimizer erzeugen."
    )
    parser.add_argument(
        "--source",
        choices=("auto", "loxone", "synthetic"),
        default="auto",
    )
    parser.add_argument("--output", default=None)
    parser.add_argument("--synthetic-start", type=_parse_date, default=None)
    parser.add_argument("--synthetic-end", type=_parse_date, default=None)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print_stats(args.output)
        return

    generate(
        source=args.source,
        output=args.output,
        synthetic_start=args.synthetic_start,
        synthetic_end=args.synthetic_end,
    )
    print_stats(args.output or get_output_path())


if __name__ == "__main__":
    main()
