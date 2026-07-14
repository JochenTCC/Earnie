"""Walk-forward-Evaluation: Preisprognose vs. Spiegelung."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from data.market_prices import MAX_MIRROR_LOOKBACK_DAYS
from data.price_forecast_model import (
    FEATURE_VARIANT_BASE,
    FEATURE_VARIANT_EXTENDED,
    TARGET_COLUMN,
    PriceForecastModel,
    bias_metrics,
    fit_price_model,
    peak_regression_metrics,
    predict_prices,
    regression_metrics,
)


def mirror_baseline_prices(
    frame: pd.DataFrame,
    *,
    price_lookup: pd.Series | None = None,
) -> pd.Series:
    """Spiegel-Baseline: gleiche Uhrzeit an vorherigen Tagen (wie Live)."""
    lookup = price_lookup if price_lookup is not None else frame[TARGET_COLUMN]
    by_slot = lookup.to_dict()
    mirrored: list[float | None] = []
    for slot in frame.index:
        price = None
        for days_back in range(1, MAX_MIRROR_LOOKBACK_DAYS + 1):
            candidate = slot - timedelta(days=days_back)
            if candidate in by_slot:
                price = float(by_slot[candidate])
                break
        if price is None:
            raise ValueError(
                f"Keine Spiegelquelle für {slot} innerhalb von "
                f"{MAX_MIRROR_LOOKBACK_DAYS} Tagen."
            )
        mirrored.append(price)
    return pd.Series(mirrored, index=frame.index, name="mirror_price")


def evaluate_strategies(
    frame: pd.DataFrame,
    *,
    model: PriceForecastModel | None = None,
    price_lookup: pd.Series | None = None,
    peak_percentile: float = 90.0,
) -> dict[str, Any]:
    """Vergleicht Modell (optional) und Spiegelung gegen Ist-Preise."""
    actual = frame[TARGET_COLUMN].to_numpy(dtype=float)
    lookup = price_lookup if price_lookup is not None else frame[TARGET_COLUMN]
    mirror = mirror_baseline_prices(frame, price_lookup=lookup).to_numpy(dtype=float)
    report: dict[str, Any] = {
        "rows": len(frame),
        "range_start": frame.index[0].isoformat(),
        "range_end": frame.index[-1].isoformat(),
        "mirror": regression_metrics(actual, mirror),
        "mirror_peak": peak_regression_metrics(actual, mirror, percentile=peak_percentile),
    }
    if model is not None:
        predicted_raw = predict_prices(model, frame, apply_bias_correction=False)
        predicted = predict_prices(model, frame, apply_bias_correction=True)
        report["model"] = regression_metrics(actual, predicted)
        report["model_bias"] = bias_metrics(actual, predicted)
        report["model_peak"] = peak_regression_metrics(
            actual, predicted, percentile=peak_percentile
        )
        report["model_raw"] = regression_metrics(actual, predicted_raw)
        report["model_raw_bias"] = bias_metrics(actual, predicted_raw)
        report["feature_variant"] = model.feature_variant
        report["bias_correction_cent_kwh"] = model.bias_correction_cent_kwh
        report["model_vs_mirror_mae_delta"] = (
            report["mirror"]["mae_cent_kwh"] - report["model"]["mae_cent_kwh"]
        )
    return report


def walk_forward_evaluate(
    frame: pd.DataFrame,
    *,
    train_days: int,
    test_days: int,
    feature_variant: str = FEATURE_VARIANT_EXTENDED,
) -> dict[str, Any]:
    """
    Rollierendes Training: je Fenster train_days trainieren, test_days testen.
    """
    if train_days < 7:
        raise ValueError("train_days muss mindestens 7 sein.")
    if test_days < 1:
        raise ValueError("test_days muss mindestens 1 sein.")
    train_hours = train_days * 24
    test_hours = test_days * 24
    if len(frame) < train_hours + test_hours:
        raise ValueError(
            f"Dataset zu kurz ({len(frame)} h) für "
            f"{train_days}+{test_days} Tage Walk-forward."
        )

    model_errors: list[float] = []
    mirror_errors: list[float] = []
    folds = 0
    cursor = train_hours
    while cursor + test_hours <= len(frame):
        train = frame.iloc[cursor - train_hours : cursor]
        test = frame.iloc[cursor : cursor + test_hours]
        model = fit_price_model(train, feature_variant=feature_variant)
        fold_report = evaluate_strategies(
            test,
            model=model,
            price_lookup=frame[TARGET_COLUMN],
        )
        model_errors.append(fold_report["model"]["mae_cent_kwh"])
        mirror_errors.append(fold_report["mirror"]["mae_cent_kwh"])
        folds += 1
        cursor += test_hours

    return {
        "folds": folds,
        "train_days": train_days,
        "test_days": test_days,
        "feature_variant": feature_variant,
        "mean_model_mae_cent_kwh": float(np.mean(model_errors)),
        "mean_mirror_mae_cent_kwh": float(np.mean(mirror_errors)),
        "mean_mae_delta_model_better": float(np.mean(mirror_errors) - np.mean(model_errors)),
        "model_wins_folds": int(sum(m < mir for m, mir in zip(model_errors, mirror_errors))),
    }


def chronological_split_evaluate(
    frame: pd.DataFrame,
    *,
    train_ratio: float = 0.8,
    feature_variant: str = FEATURE_VARIANT_EXTENDED,
) -> dict[str, Any]:
    """Einfacher chronologischer Split: train → fit, test → evaluieren."""
    if not 0.5 <= train_ratio < 1.0:
        raise ValueError("train_ratio muss in [0.5, 1.0) liegen.")
    split = max(1, int(len(frame) * train_ratio))
    if split >= len(frame):
        raise ValueError("Dataset zu kurz für chronologischen Split.")
    train = frame.iloc[:split]
    test = frame.iloc[split:]
    model = fit_price_model(train, feature_variant=feature_variant)
    report = evaluate_strategies(test, model=model, price_lookup=frame[TARGET_COLUMN])
    report["split"] = {
        "train_rows": len(train),
        "test_rows": len(test),
        "train_ratio": train_ratio,
    }
    return report


def compare_feature_variants(
    frame: pd.DataFrame,
    *,
    train_ratio: float = 0.8,
    train_days: int = 90,
    test_days: int = 7,
) -> dict[str, Any]:
    """Vergleicht base vs. extended vs. Spiegelung (Holdout + Walk-forward)."""
    variants = [FEATURE_VARIANT_BASE]
    if all(col in frame.columns for col in ("eu_load_mw", "eu_residual_load_mw")):
        variants.append(FEATURE_VARIANT_EXTENDED)
    holdout: dict[str, Any] = {}
    walk_forward: dict[str, Any] = {}
    for variant in variants:
        holdout[variant] = chronological_split_evaluate(
            frame,
            train_ratio=train_ratio,
            feature_variant=variant,
        )
        try:
            walk_forward[variant] = walk_forward_evaluate(
                frame,
                train_days=train_days,
                test_days=test_days,
                feature_variant=variant,
            )
        except ValueError as exc:
            walk_forward[variant] = {"error": str(exc)}
    return {
        "rows": len(frame),
        "holdout": holdout,
        "walk_forward": walk_forward,
    }
