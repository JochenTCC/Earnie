"""OLS-Preisprognosemodell (EU-Wetter & Erzeugung) — Spec: price-forecast-renewables."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MODEL_VERSION = 2
TARGET_COLUMN = "price_epex_cent_kwh"
FEATURE_VARIANT_BASE = "base"
FEATURE_VARIANT_EXTENDED = "extended"
DEFAULT_BIAS_PEAK_PERCENTILE = 90.0

RAW_RENEWABLE_WEATHER_COLUMNS: tuple[str, ...] = (
    "eu_wind_mw",
    "eu_solar_mw",
    "eu_wind_speed_kmh",
    "eu_shortwave_radiation_wm2",
)
RAW_LOAD_COLUMNS: tuple[str, ...] = (
    "eu_load_mw",
    "eu_residual_load_mw",
)
DERIVED_FEATURE_COLUMNS: tuple[str, ...] = (
    "hour_sin",
    "hour_cos",
    "weekday",
    "month",
)

# Default für neue Modelle
FEATURE_COLUMNS: tuple[str, ...] = (
    RAW_RENEWABLE_WEATHER_COLUMNS + RAW_LOAD_COLUMNS + DERIVED_FEATURE_COLUMNS
)


def feature_columns_for_variant(variant: str) -> tuple[str, ...]:
    if variant == FEATURE_VARIANT_BASE:
        return RAW_RENEWABLE_WEATHER_COLUMNS + DERIVED_FEATURE_COLUMNS
    if variant == FEATURE_VARIANT_EXTENDED:
        return RAW_RENEWABLE_WEATHER_COLUMNS + RAW_LOAD_COLUMNS + DERIVED_FEATURE_COLUMNS
    raise ValueError(
        f"Unbekannte feature_variant '{variant}' "
        f"(erwartet '{FEATURE_VARIANT_BASE}' oder '{FEATURE_VARIANT_EXTENDED}')."
    )


def feature_name_tuple(variant: str) -> tuple[str, ...]:
    return ("intercept",) + feature_columns_for_variant(variant)


def _required_raw_columns(variant: str) -> tuple[str, ...]:
    if variant == FEATURE_VARIANT_BASE:
        return RAW_RENEWABLE_WEATHER_COLUMNS
    return RAW_RENEWABLE_WEATHER_COLUMNS + RAW_LOAD_COLUMNS


def resolve_feature_variant(frame: pd.DataFrame) -> str:
    """extended wenn Last-Spalten vorhanden, sonst base."""
    if all(col in frame.columns for col in RAW_LOAD_COLUMNS):
        return FEATURE_VARIANT_EXTENDED
    return FEATURE_VARIANT_BASE


@dataclass(frozen=True)
class PriceForecastModel:
    """Trainiertes lineares Preismodell (EPEX Cent/kWh)."""

    version: int
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    trained_range_start: str
    trained_range_end: str
    training_rows: int
    feature_variant: str = FEATURE_VARIANT_EXTENDED
    bias_correction_cent_kwh: float = 0.0
    bias_correction_peak_percentile: float = DEFAULT_BIAS_PEAK_PERCENTILE
    bias_correction_peak_threshold_cent_kwh: float | None = None
    bias_correction_non_peak_hours: int = 0

    def predict_raw(self, features: np.ndarray) -> np.ndarray:
        return self.predict_matrix(features)

    def predict_adjusted(self, features: np.ndarray) -> np.ndarray:
        return self.predict_raw(features) + self.bias_correction_cent_kwh

    def predict_matrix(self, features: np.ndarray) -> np.ndarray:
        if features.shape[1] != len(self.coefficients):
            raise ValueError(
                f"Feature-Matrix hat {features.shape[1]} Spalten, "
                f"erwartet {len(self.coefficients)}."
            )
        return features @ np.asarray(self.coefficients, dtype=float)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "feature_names": list(self.feature_names),
            "coefficients": list(self.coefficients),
            "trained_range_start": self.trained_range_start,
            "trained_range_end": self.trained_range_end,
            "training_rows": self.training_rows,
            "feature_variant": self.feature_variant,
        }
        if self.bias_correction_cent_kwh != 0.0 or self.bias_correction_non_peak_hours > 0:
            payload["bias_correction_cent_kwh"] = self.bias_correction_cent_kwh
            payload["bias_correction_peak_percentile"] = self.bias_correction_peak_percentile
            if self.bias_correction_peak_threshold_cent_kwh is not None:
                payload["bias_correction_peak_threshold_cent_kwh"] = (
                    self.bias_correction_peak_threshold_cent_kwh
                )
            payload["bias_correction_non_peak_hours"] = self.bias_correction_non_peak_hours
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PriceForecastModel:
        threshold = payload.get("bias_correction_peak_threshold_cent_kwh")
        return cls(
            version=int(payload["version"]),
            feature_names=tuple(payload["feature_names"]),
            coefficients=tuple(float(c) for c in payload["coefficients"]),
            trained_range_start=str(payload["trained_range_start"]),
            trained_range_end=str(payload["trained_range_end"]),
            training_rows=int(payload["training_rows"]),
            feature_variant=str(payload.get("feature_variant", FEATURE_VARIANT_BASE)),
            bias_correction_cent_kwh=float(payload.get("bias_correction_cent_kwh", 0.0)),
            bias_correction_peak_percentile=float(
                payload.get("bias_correction_peak_percentile", DEFAULT_BIAS_PEAK_PERCENTILE)
            ),
            bias_correction_peak_threshold_cent_kwh=(
                float(threshold) if threshold is not None else None
            ),
            bias_correction_non_peak_hours=int(
                payload.get("bias_correction_non_peak_hours", 0)
            ),
        )


def load_training_dataset(
    path: Path,
    *,
    feature_variant: str = FEATURE_VARIANT_EXTENDED,
) -> pd.DataFrame:
    """Lädt ein von build_price_training_dataset erzeugtes CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Training-Dataset nicht gefunden: {path}")
    frame = pd.read_csv(path, parse_dates=["slot_datetime"])
    frame = frame.set_index("slot_datetime").sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True)
    elif frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    required = (*_required_raw_columns(feature_variant), TARGET_COLUMN)
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f"Dataset-Spalten fehlen: {', '.join(missing)}")
    return frame


def enrich_model_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Ergänzt zyklische Stundenfeatures; weekday/month aus Index falls nötig."""
    enriched = frame.copy()
    if "hour" not in enriched.columns:
        enriched["hour"] = enriched.index.hour
    if "weekday" not in enriched.columns:
        enriched["weekday"] = enriched.index.weekday
    if "month" not in enriched.columns:
        enriched["month"] = enriched.index.month
    hours = enriched["hour"].to_numpy(dtype=float)
    enriched["hour_sin"] = np.sin(2.0 * math.pi * hours / 24.0)
    enriched["hour_cos"] = np.cos(2.0 * math.pi * hours / 24.0)
    return enriched


def build_feature_matrix(
    frame: pd.DataFrame,
    feature_names: tuple[str, ...],
) -> np.ndarray:
    """Design-Matrix inkl. Intercept (erste Spalte in feature_names)."""
    enriched = enrich_model_features(frame)
    columns = [np.ones(len(enriched), dtype=float)]
    for name in feature_names:
        if name == "intercept":
            continue
        columns.append(enriched[name].to_numpy(dtype=float))
    return np.column_stack(columns)


def compute_bias_correction(
    actual: np.ndarray,
    predicted: np.ndarray,
    *,
    peak_percentile: float = DEFAULT_BIAS_PEAK_PERCENTILE,
) -> dict[str, float | int]:
    """
    Additive Bias-Korrektur aus Nicht-Peak-Stunden (Ist-Preis unter Perzentil).

    Peaks (obere Preis-Quantile) werden ausgeschlossen, damit extreme Stunden
    den Mittelwert nicht dominieren.
    """
    if len(actual) != len(predicted):
        raise ValueError("actual und predicted müssen gleiche Länge haben.")
    if len(actual) == 0:
        raise ValueError("Keine Werte für Bias-Korrektur.")
    if not 0.0 < peak_percentile < 100.0:
        raise ValueError("peak_percentile muss in (0, 100) liegen.")
    threshold = float(np.percentile(actual, peak_percentile))
    mask = actual < threshold
    if not np.any(mask):
        raise ValueError(
            f"Keine Nicht-Peak-Stunden für Bias-Korrektur (Perzentil {peak_percentile})."
        )
    correction = float(np.mean(actual[mask] - predicted[mask]))
    return {
        "bias_correction_cent_kwh": correction,
        "bias_correction_peak_percentile": peak_percentile,
        "bias_correction_peak_threshold_cent_kwh": threshold,
        "bias_correction_non_peak_hours": int(mask.sum()),
    }


def fit_price_model(
    frame: pd.DataFrame,
    *,
    feature_variant: str = FEATURE_VARIANT_EXTENDED,
    bias_peak_percentile: float = DEFAULT_BIAS_PEAK_PERCENTILE,
    apply_bias_correction: bool = True,
) -> PriceForecastModel:
    """OLS auf dem übergebenen DataFrame."""
    if frame.empty:
        raise ValueError("fit_price_model erfordert mindestens eine Zeile.")
    names = feature_name_tuple(feature_variant)
    raw_required = _required_raw_columns(feature_variant)
    missing = [c for c in raw_required if c not in frame.columns]
    if TARGET_COLUMN not in frame.columns:
        missing.append(TARGET_COLUMN)
    if missing:
        raise ValueError(f"Features fehlen im DataFrame: {', '.join(missing)}")
    matrix = build_feature_matrix(frame, names)
    targets = frame[TARGET_COLUMN].to_numpy(dtype=float)
    coefficients, _, _, _ = np.linalg.lstsq(matrix, targets, rcond=None)
    index = frame.index
    model = PriceForecastModel(
        version=MODEL_VERSION,
        feature_names=names,
        coefficients=tuple(float(c) for c in coefficients),
        trained_range_start=index[0].isoformat(),
        trained_range_end=index[-1].isoformat(),
        training_rows=len(frame),
        feature_variant=feature_variant,
    )
    if not apply_bias_correction:
        return model
    raw_predicted = model.predict_raw(matrix)
    bias = compute_bias_correction(
        targets,
        raw_predicted,
        peak_percentile=bias_peak_percentile,
    )
    return PriceForecastModel(
        version=model.version,
        feature_names=model.feature_names,
        coefficients=model.coefficients,
        trained_range_start=model.trained_range_start,
        trained_range_end=model.trained_range_end,
        training_rows=model.training_rows,
        feature_variant=model.feature_variant,
        bias_correction_cent_kwh=float(bias["bias_correction_cent_kwh"]),
        bias_correction_peak_percentile=float(bias["bias_correction_peak_percentile"]),
        bias_correction_peak_threshold_cent_kwh=float(
            bias["bias_correction_peak_threshold_cent_kwh"]
        ),
        bias_correction_non_peak_hours=int(bias["bias_correction_non_peak_hours"]),
    )


def predict_prices(
    model: PriceForecastModel,
    frame: pd.DataFrame,
    *,
    apply_bias_correction: bool = True,
) -> np.ndarray:
    matrix = build_feature_matrix(frame, model.feature_names)
    if apply_bias_correction:
        return model.predict_adjusted(matrix)
    return model.predict_raw(matrix)


def save_price_model(model: PriceForecastModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(model.to_dict(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_price_model(path: Path) -> PriceForecastModel:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    model = PriceForecastModel.from_dict(payload)
    if model.version not in (1, MODEL_VERSION):
        raise ValueError(
            f"Preismodell-Version {model.version} wird nicht unterstützt "
            f"(erwartet 1 oder {MODEL_VERSION})."
        )
    return model


def bias_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Mittlerer und medianer Fehler (predicted - actual)."""
    if len(actual) != len(predicted):
        raise ValueError("actual und predicted müssen gleiche Länge haben.")
    if len(actual) == 0:
        raise ValueError("Keine Werte für Bias-Metriken.")
    errors = predicted - actual
    return {
        "bias_mean_cent_kwh": float(np.mean(errors)),
        "bias_median_cent_kwh": float(np.median(errors)),
    }


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """MAE, RMSE und MAPE (nur wo |actual| > 0.5 Cent/kWh)."""
    if len(actual) != len(predicted):
        raise ValueError("actual und predicted müssen gleiche Länge haben.")
    if len(actual) == 0:
        raise ValueError("Keine Werte für Metriken.")
    errors = predicted - actual
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    mask = np.abs(actual) > 0.5
    if np.any(mask):
        mape = float(
            np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100.0
        )
    else:
        mape = float("nan")
    return {"mae_cent_kwh": mae, "rmse_cent_kwh": rmse, "mape_percent": mape}


def peak_regression_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    *,
    percentile: float = 90.0,
) -> dict[str, float]:
    """Metriken nur für obere Preis-Quantile (Peak-Stunden)."""
    if len(actual) == 0:
        raise ValueError("Keine Werte für Peak-Metriken.")
    threshold = float(np.percentile(actual, percentile))
    mask = actual >= threshold
    if not np.any(mask):
        return {
            "peak_percentile": percentile,
            "peak_threshold_cent_kwh": threshold,
            "peak_hours": 0.0,
            "mae_cent_kwh": float("nan"),
            "rmse_cent_kwh": float("nan"),
        }
    metrics = regression_metrics(actual[mask], predicted[mask])
    metrics["peak_percentile"] = percentile
    metrics["peak_threshold_cent_kwh"] = threshold
    metrics["peak_hours"] = float(mask.sum())
    return metrics
