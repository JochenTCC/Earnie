"""Vergleichsdaten für Preisprognose-Visualisierung (Phase 3)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from data.price_forecast_eval import evaluate_strategies, mirror_baseline_prices
from data.price_forecast_model import (
    TARGET_COLUMN,
    PriceForecastModel,
    fit_price_model,
    load_price_model,
    load_training_dataset,
    predict_prices,
    regression_metrics,
    resolve_feature_variant,
)

DEFAULT_CACHE_DIR = Path("data/cache")
DEFAULT_MODEL_PATH = DEFAULT_CACHE_DIR / "price_model_coefficients.json"


def feature_variant_for_frame(frame: pd.DataFrame) -> str:
    return resolve_feature_variant(frame)


@dataclass(frozen=True)
class ForecastEvaluation:
    """Train/Test-Split mit Ist-, Modell- und Spiegelpreisen."""

    train: pd.DataFrame
    test: pd.DataFrame
    model: PriceForecastModel
    model_metrics: dict[str, float]
    mirror_metrics: dict[str, float]


def list_training_datasets(cache_dir: Path = DEFAULT_CACHE_DIR) -> list[Path]:
    if not cache_dir.exists():
        return []
    return sorted(cache_dir.glob("price_training_*.csv"), key=lambda p: p.stat().st_mtime)


def resolve_dataset_path(selected: Path | None) -> Path:
    if selected is not None:
        return selected
    datasets = list_training_datasets()
    if not datasets:
        raise FileNotFoundError(
            "Kein Training-Dataset in data/cache/. "
            "Zuerst: python -m scripts.build_price_training_dataset"
        )
    return datasets[-1]


def split_train_test(
    frame: pd.DataFrame,
    *,
    train_ratio: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0.5 <= train_ratio < 1.0:
        raise ValueError("train_ratio muss in [0.5, 1.0) liegen.")
    split = max(24, int(len(frame) * train_ratio))
    if split >= len(frame):
        raise ValueError("Dataset zu kurz für den gewählten Train-Anteil.")
    return frame.iloc[:split].copy(), frame.iloc[split:].copy()


def attach_forecast_columns(
    frame: pd.DataFrame,
    *,
    model: PriceForecastModel,
    price_lookup: pd.Series,
) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["actual_cent_kwh"] = enriched[TARGET_COLUMN]
    enriched["model_cent_kwh"] = predict_prices(model, enriched)
    enriched["mirror_cent_kwh"] = mirror_baseline_prices(
        enriched,
        price_lookup=price_lookup,
    )
    enriched["model_error"] = enriched["model_cent_kwh"] - enriched["actual_cent_kwh"]
    enriched["mirror_error"] = enriched["mirror_cent_kwh"] - enriched["actual_cent_kwh"]
    return enriched


def build_forecast_evaluation(
    frame: pd.DataFrame,
    *,
    train_ratio: float = 0.8,
    model: PriceForecastModel | None = None,
) -> ForecastEvaluation:
    train, test = split_train_test(frame, train_ratio=train_ratio)
    variant = feature_variant_for_frame(train)
    fitted = model if model is not None else fit_price_model(train, feature_variant=variant)
    test_enriched = attach_forecast_columns(
        test,
        model=fitted,
        price_lookup=frame[TARGET_COLUMN],
    )
    actual = test_enriched["actual_cent_kwh"].to_numpy(dtype=float)
    model_pred = test_enriched["model_cent_kwh"].to_numpy(dtype=float)
    mirror_pred = test_enriched["mirror_cent_kwh"].to_numpy(dtype=float)
    return ForecastEvaluation(
        train=train,
        test=test_enriched,
        model=fitted,
        model_metrics=regression_metrics(actual, model_pred),
        mirror_metrics=regression_metrics(actual, mirror_pred),
    )


def hourly_error_summary(test: pd.DataFrame) -> pd.DataFrame:
    grouped = test.groupby(test.index.hour).agg(
        model_mae=("model_error", lambda s: float(np.mean(np.abs(s)))),
        mirror_mae=("mirror_error", lambda s: float(np.mean(np.abs(s)))),
    )
    grouped.index.name = "hour"
    return grouped.reset_index()


def load_model_or_fit(train: pd.DataFrame, model_path: Path | None) -> PriceForecastModel:
    variant = feature_variant_for_frame(train)
    if model_path is not None and model_path.exists():
        loaded = load_price_model(model_path)
        if loaded.feature_variant == variant:
            return loaded
    return fit_price_model(train, feature_variant=variant)
