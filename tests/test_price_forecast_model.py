"""Tests für OLS-Preisprognose und Evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from data.price_forecast_eval import (
    chronological_split_evaluate,
    compare_feature_variants,
    mirror_baseline_prices,
)
from data.price_forecast_model import (
    TARGET_COLUMN,
    fit_price_model,
    load_price_model,
    predict_prices,
    save_price_model,
)

VIENNA = ZoneInfo("Europe/Vienna")


def _synthetic_frame(hours: int = 72) -> pd.DataFrame:
    start = datetime(2025, 7, 1, 0, 0, tzinfo=VIENNA)
    index = pd.DatetimeIndex(
        [start + timedelta(hours=i) for i in range(hours)],
        name="slot_datetime",
    )
    frame = pd.DataFrame(index=index)
    frame["eu_wind_mw"] = 10000.0 + np.arange(hours) * 10.0
    frame["eu_solar_mw"] = np.maximum(0.0, 20000.0 - np.abs(np.arange(hours) - 12) * 800.0)
    frame["eu_wind_speed_kmh"] = 15.0 + np.sin(np.arange(hours) / 5.0)
    frame["eu_shortwave_radiation_wm2"] = np.maximum(0.0, 400.0 * np.sin(np.arange(hours) / 12.0))
    frame["eu_load_mw"] = 45000.0 + 500.0 * np.sin(np.arange(hours) / 8.0)
    frame["eu_residual_load_mw"] = (
        frame["eu_load_mw"] - frame["eu_wind_mw"] - frame["eu_solar_mw"]
    )
    frame["hour"] = frame.index.hour
    frame["weekday"] = frame.index.weekday
    frame["month"] = frame.index.month
    frame[TARGET_COLUMN] = (
        8.0
        - 0.0002 * frame["eu_wind_mw"]
        - 0.0001 * frame["eu_solar_mw"]
        + 0.00015 * frame["eu_residual_load_mw"]
        + 0.05 * frame["hour"]
    )
    return frame


def test_fit_and_predict_recovers_linear_relationship():
    frame = _synthetic_frame(96)
    model = fit_price_model(frame)
    predicted = predict_prices(model, frame)
    assert len(predicted) == len(frame)
    assert np.mean(np.abs(predicted - frame[TARGET_COLUMN])) < 0.5


def test_save_and_load_roundtrip(tmp_path):
    frame = _synthetic_frame(48)
    model = fit_price_model(frame)
    path = tmp_path / "model.json"
    save_price_model(model, path)
    loaded = load_price_model(path)
    assert loaded.coefficients == model.coefficients
    assert loaded.feature_names == model.feature_names
    assert loaded.bias_correction_cent_kwh == model.bias_correction_cent_kwh


def test_bias_correction_zeros_non_peak_mean_on_train():
    frame = _synthetic_frame(200)
    model = fit_price_model(frame)
    actual = frame[TARGET_COLUMN].to_numpy(dtype=float)
    predicted = predict_prices(model, frame)
    threshold = model.bias_correction_peak_threshold_cent_kwh
    assert threshold is not None
    mask = actual < threshold
    non_peak_bias = float(np.mean(predicted[mask] - actual[mask]))
    assert abs(non_peak_bias) < 1e-9


def test_load_model_version_one_without_bias_fields(tmp_path):
    frame = _synthetic_frame(48)
    model = fit_price_model(frame, apply_bias_correction=False)
    path = tmp_path / "v1.json"
    payload = model.to_dict()
    payload["version"] = 1
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    loaded = load_price_model(path)
    assert loaded.bias_correction_cent_kwh == 0.0


def test_mirror_baseline_uses_previous_day():
    frame = _synthetic_frame(48)
    mirrored = mirror_baseline_prices(frame.iloc[24:], price_lookup=frame[TARGET_COLUMN])
    for slot, price in mirrored.items():
        expected = float(frame.loc[slot - timedelta(days=1), TARGET_COLUMN])
        assert price == expected


def test_chronological_split_produces_model_metrics():
    frame = _synthetic_frame(120)
    report = chronological_split_evaluate(frame, train_ratio=0.75)
    assert "model" in report
    assert "mirror" in report
    assert report["split"]["test_rows"] == 30


def test_evaluate_strategies_requires_mirror_history():
    frame = _synthetic_frame(10)
    with pytest.raises(ValueError, match="Spiegelquelle"):
        mirror_baseline_prices(frame.iloc[:2])


def test_compare_feature_variants_reports_base_and_extended():
    frame = _synthetic_frame(200)
    report = compare_feature_variants(frame, train_ratio=0.8, train_days=30, test_days=3)
    assert "base" in report["holdout"]
    assert "extended" in report["holdout"]
    assert report["holdout"]["extended"]["model"]["mae_cent_kwh"] < 1.0
