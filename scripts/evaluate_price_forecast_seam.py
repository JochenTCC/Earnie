#!/usr/bin/env python3
"""Backtest of the live price-forecast correction at the Day-Ahead seam.

Compares the constant rolling bias (window before the planning start, as before 2026-11-28) with
the seam correction of ``data.market_prices`` (bias window ending at the first predicted slot,
first slot at the residual of the last known hours, linear decay into the bias), on archive
features of a training CSV (``scripts.build_price_training_dataset``).

Ticks are the local hours 00..12 of every day: tomorrow's Day-Ahead is not yet published, known
prices end at local midnight and the horizon ends at tick + 36 h. Hourly resolution, cap 12 ct.

    python -m scripts.evaluate_price_forecast_seam --dataset data/cache/price_training_X.csv
"""
from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from data.price_forecast_model import TARGET_COLUMN, load_price_model, load_training_dataset, predict_prices

BUCKETS = (("0-3h", 0, 3), ("3-6h", 3, 6), ("6-12h", 6, 12), ("12h+", 12, 10_000))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path("share/data/price_model_coefficients.json"))
    parser.add_argument("--start", default=None, help="first tick day (local, YYYY-MM-DD)")
    parser.add_argument("--lookback-hours", type=int, default=48)
    parser.add_argument("--cap", type=float, default=12.0)
    parser.add_argument("--horizon-hours", type=int, default=36)
    parser.add_argument("--seam-hours", type=int, nargs="+", default=[1, 2, 3, 4, 6])
    parser.add_argument("--decay-hours", type=float, nargs="+", default=[3, 6, 8, 12, 18, 24])
    parser.add_argument("--tz", default="Europe/Vienna")
    return parser.parse_args(argv)


def evaluate(args: argparse.Namespace) -> pd.DataFrame:
    frame = load_training_dataset(args.dataset)
    model = load_price_model(args.model)
    pred = predict_prices(model, frame)
    actual = frame[TARGET_COLUMN].to_numpy()
    resid = actual - pred
    local = frame.index.tz_convert(args.tz)
    pos = {ts: i for i, ts in enumerate(frame.index)}
    lb, cap = args.lookback_hours, args.cap

    def clip(value: float) -> float:
        return float(np.clip(value, -cap, cap))

    variants: dict[str, tuple] = {"constant (window before start)": ("start", None, None)}
    variants["constant (window to seam)"] = ("seam_window", None, None)
    for k, d in product(args.seam_hours, args.decay_hours):
        variants[f"seam K{k} D{d:g}"] = ("seam", k, d)

    errors = {name: {b[0]: [] for b in (("all", 0, 0), *BUCKETS)} for name in variants}
    jump_err = {name: [] for name in variants}
    start = pd.Timestamp(args.start, tz=args.tz) if args.start else None
    for i, ts in enumerate(local):
        if ts.hour > 12 or (start is not None and ts < start):
            continue
        seam = pos.get((ts + pd.Timedelta(days=1)).normalize().tz_convert("UTC"))
        end = min(i + args.horizon_hours, len(actual))
        if seam is None or i < lb or seam < lb or end <= seam:
            continue
        hours = np.arange(end - seam)
        bias_start = clip(resid[i - lb : i].mean())
        bias_seam = clip(resid[seam - lb : seam].mean())
        for name, (kind, k, d) in variants.items():
            if kind == "start":
                offset = np.full(len(hours), bias_start)
            elif kind == "seam_window":
                offset = np.full(len(hours), bias_seam)
            else:
                anchor = clip(resid[seam - k : seam].mean())
                offset = bias_seam + (anchor - bias_seam) * np.clip(1.0 - hours / d, 0.0, 1.0)
            forecast = pred[seam:end] + offset
            err = np.abs(forecast - actual[seam:end])
            errors[name]["all"].extend(err)
            for label, lo, hi in BUCKETS:
                errors[name][label].extend(err[(hours >= lo) & (hours < hi)])
            jump_err[name].append(abs(forecast[0] - actual[seam]))
    rows = {
        name: {label: float(np.mean(values)) for label, values in buckets.items()}
        | {"first slot": float(np.mean(jump_err[name]))}
        for name, buckets in errors.items()
    }
    return pd.DataFrame.from_dict(rows, orient="index").rename(columns={"all": "MAE"})


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    table = evaluate(args)
    print(f"Dataset {args.dataset}, start {args.start or 'all'}; MAE in ct/kWh (EPEX)")
    print(table.iloc[:2].round(3).to_string())
    print("--- seam variants, best 10 by MAE")
    print(table.iloc[2:].sort_values("MAE").head(10).round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
