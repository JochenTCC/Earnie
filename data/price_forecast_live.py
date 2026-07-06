"""Live-Vorbereitung: Preisprognose für fehlende Day-Ahead-Slots (Phase 3)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data.market_prices import PRICE_SOURCE_DAY_AHEAD, PRICE_SOURCE_MIRRORED
from data.price_forecast_model import (
    PriceForecastModel,
    load_price_model,
    predict_prices,
)

from data.market_prices import PRICE_SOURCE_PREDICTED
MISSING_PRICE_STRATEGY_MIRROR = "mirror"
MISSING_PRICE_STRATEGY_FORECAST = "forecast"
DEFAULT_MODEL_PATH = Path("data/cache/price_model_coefficients.json")


def get_missing_price_strategy() -> str:
    """
    Liest market_prices.missing_price_strategy aus config.json.
    Standard: forecast (OLS); ohne Block ebenfalls forecast.
    """
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get("market_prices")
    if not isinstance(block, dict):
        return MISSING_PRICE_STRATEGY_FORECAST
    strategy = str(block.get("missing_price_strategy", MISSING_PRICE_STRATEGY_FORECAST)).strip()
    if strategy not in (MISSING_PRICE_STRATEGY_MIRROR, MISSING_PRICE_STRATEGY_FORECAST):
        raise ValueError(
            "market_prices.missing_price_strategy muss 'mirror' oder 'forecast' sein."
        )
    return strategy


def get_forecast_model_path() -> Path:
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get("market_prices")
    if isinstance(block, dict) and block.get("forecast_model_path"):
        return Path(str(block["forecast_model_path"]))
    return DEFAULT_MODEL_PATH


def load_configured_model() -> PriceForecastModel | None:
    path = get_forecast_model_path()
    if not path.exists():
        return None
    return load_price_model(path)


def _align_live_feature_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Index auf naive Planungszeitzone (passend zu Live-Slots)."""
    import config

    tz_name = config.get_planning_timezone()
    idx = frame.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    localized = idx.tz_convert(tz_name).tz_localize(None)
    aligned = frame.copy()
    aligned.index = localized
    return aligned


def build_live_feature_frame_for_slots(slot_datetimes: list) -> pd.DataFrame | None:
    """EU-Features für OLS-Prognose fehlender Day-Ahead-Slots (ohne AT-Preise)."""
    from datetime import timedelta

    import requests

    from data.eu_market_features import fetch_eu_power_hourly, fetch_eu_weather_hourly
    from data.market_prices import normalize_price_slot
    from data.price_forecast_model import enrich_model_features

    if not slot_datetimes:
        return None

    slots = [normalize_price_slot(dt) for dt in slot_datetimes]
    start = min(slot.date() for slot in slots)
    end = max(slot.date() for slot in slots) + timedelta(days=1)
    try:
        power = fetch_eu_power_hourly(start, end)
        weather = fetch_eu_weather_hourly(start, end)
        merged = power.join(weather, how="inner")
        if merged.empty:
            return None
        return enrich_model_features(_align_live_feature_index(merged))
    except (OSError, ValueError, requests.HTTPError) as exc:
        print(
            f"⚠️ Preisprognose: EU-Features nicht ladbar ({exc}) — "
            "Spiegelung als Fallback für fehlende Slots."
        )
        return None


def resolve_market_slots_kwargs(target_hours: list) -> dict:
    """Kwargs für market_prices.resolve_market_slots aus config.json."""
    strategy = get_missing_price_strategy()
    kwargs: dict = {"missing_price_strategy": strategy}
    if strategy != MISSING_PRICE_STRATEGY_FORECAST:
        return kwargs

    model_path = get_forecast_model_path()
    model = load_configured_model()
    if model is None:
        print(
            f"⚠️ Preisprognose: Modell nicht gefunden ({model_path}) — "
            "Fallback Spiegelung."
        )
        kwargs["missing_price_strategy"] = MISSING_PRICE_STRATEGY_MIRROR
        return kwargs

    kwargs["forecast_model"] = model
    kwargs["forecast_model_path"] = model_path
    feature_frame = build_live_feature_frame_for_slots(target_hours)
    if feature_frame is not None and not feature_frame.empty:
        kwargs["forecast_feature_frame"] = feature_frame
    return kwargs


def predict_epex_cent_for_features(frame: pd.DataFrame, model: PriceForecastModel) -> list[float]:
    return [float(v) for v in predict_prices(model, frame)]


def build_predicted_slot(
    slot_datetime,
    epex_cent: float,
    *,
    model_path: Path | None = None,
) -> dict[str, Any]:
    """Erzeugt einen resolve_market_slots-kompatiblen Preis-Slot."""
    from data.market_prices import epex_to_brutto_cent

    row: dict[str, Any] = {
        "slot_datetime": slot_datetime,
        "hour": slot_datetime.hour,
        "price_buy": round(float(epex_cent), 4),
        "price_source": PRICE_SOURCE_PREDICTED,
        "k_act": epex_to_brutto_cent(float(epex_cent)),
    }
    if model_path is not None:
        row["forecast_model_path"] = str(model_path)
    return row


def is_extrapolated_source(price_source: str | None) -> bool:
    """Chart/UI: extrapoliert = gespiegelt oder prognostiziert."""
    return price_source in (PRICE_SOURCE_MIRRORED, PRICE_SOURCE_PREDICTED)
