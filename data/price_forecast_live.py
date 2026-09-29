"""Live-Vorbereitung: Preisprognose für fehlende Day-Ahead-Slots (Phase 3)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from data.market_prices import PRICE_SOURCE_DAY_AHEAD, PRICE_SOURCE_MIRRORED
from data.price_forecast_model import (
    PriceForecastModel,
    load_price_model,
    predict_prices,
)

from data.market_prices import PRICE_SOURCE_PREDICTED
from runtime_store.persist_paths import resolve_runtime_prefixed_path

MISSING_PRICE_STRATEGY_MIRROR = "mirror"
MISSING_PRICE_STRATEGY_FORECAST = "forecast"
DEFAULT_MODEL_PATH = Path("share/data/price_model_coefficients.json")
LEGACY_MODEL_PATH = Path("data/cache/price_model_coefficients.json")
LIVE_FEATURE_CACHE_TTL_SEC = 45 * 60

logger = logging.getLogger(__name__)

_model_fallback_warned = False
_live_feature_cache: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}
_power_day_cache: dict[date, pd.DataFrame] = {}


def _feature_load_error_summary(exc: BaseException) -> str:
    """Kurzbeschreibung für Logs (ohne volle Request-URL)."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


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
    global _model_fallback_warned
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get("market_prices")
    if isinstance(block, dict) and block.get("forecast_model_path"):
        configured = Path(resolve_runtime_prefixed_path(str(block["forecast_model_path"])))
        if configured.exists():
            return configured
        for fallback in (DEFAULT_MODEL_PATH, LEGACY_MODEL_PATH):
            if fallback.exists():
                if not _model_fallback_warned:
                    logger.warning(
                        "Preisprognose: konfiguriertes Modell fehlt (%s) — nutze %s.",
                        configured,
                        fallback,
                    )
                    _model_fallback_warned = True
                return fallback
        return configured
    if DEFAULT_MODEL_PATH.exists():
        return DEFAULT_MODEL_PATH
    return LEGACY_MODEL_PATH


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


def _archive_latest_complete_day() -> date:
    """Letzter Kalendertag mit vollständigen Open-Meteo/Energy-Charts-Archivdaten."""
    import sys
    from zoneinfo import ZoneInfo

    tz_name = "UTC"
    cfg = sys.modules.get("config")
    if (
        cfg is not None
        and getattr(cfg, "CONFIG", None) is not None
        and callable(getattr(cfg, "get_planning_timezone", None))
    ):
        try:
            tz_name = str(cfg.get_planning_timezone())
        except Exception:
            tz_name = "UTC"
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).date() - timedelta(days=1)


def _archive_covers_slot_range(slot_datetimes: list) -> bool:
    """True, wenn alle Slots durch Archive-APIs abgedeckt werden können."""
    from data.market_prices import normalize_price_slot

    if not slot_datetimes:
        return False
    latest_archive_day = _archive_latest_complete_day()
    slots = [normalize_price_slot(dt) for dt in slot_datetimes]
    return max(slot.date() for slot in slots) <= latest_archive_day


def _enrich_merged_features(merged: pd.DataFrame) -> pd.DataFrame | None:
    from data.price_forecast_model import enrich_model_features

    if merged.empty:
        return None
    return enrich_model_features(_align_live_feature_index(merged))


def _cached_eu_power_day(ref_day: date) -> pd.DataFrame:
    """Archive EU power for one calendar day (process-local cache)."""
    from data.eu_market_features import fetch_eu_power_hourly

    cached = _power_day_cache.get(ref_day)
    if cached is not None:
        return cached
    logger.info(
        "Preisprognose: lade EU-Leistungs-Archiv für %s (einmalig, gecacht)…",
        ref_day.isoformat(),
    )
    frame = fetch_eu_power_hourly(ref_day, ref_day + timedelta(days=1))
    _power_day_cache[ref_day] = frame
    return frame


def _build_archive_feature_frame(slots: list[datetime]) -> pd.DataFrame | None:
    from data.eu_market_features import fetch_eu_power_hourly, fetch_eu_weather_hourly

    start = min(slot.date() for slot in slots)
    end = max(slot.date() for slot in slots) + timedelta(days=1)
    weather = fetch_eu_weather_hourly(start, end)
    power = fetch_eu_power_hourly(start, end)
    return _enrich_merged_features(power.join(weather, how="inner"))


def _build_forecast_feature_frame(slots: list[datetime]) -> pd.DataFrame | None:
    """Live green-zone features: Open-Meteo forecast weather + hour-of-day archive power."""
    import time

    from data.eu_market_features import (
        fetch_eu_weather_forecast_hourly,
        remap_power_by_hour_of_day,
    )

    start = min(slot.date() for slot in slots)
    end = max(slot.date() for slot in slots) + timedelta(days=1)
    t0 = time.perf_counter()
    logger.info(
        "Preisprognose: Live-Features %s..%s (%d Stunden-Slots)…",
        start.isoformat(),
        (end - timedelta(days=1)).isoformat(),
        len(slots),
    )
    weather = fetch_eu_weather_forecast_hourly(start, end)
    t_weather = time.perf_counter() - t0
    ref_day = _archive_latest_complete_day()
    power_ref = _cached_eu_power_day(ref_day)
    power = remap_power_by_hour_of_day(power_ref, slots)
    merged = power.join(weather, how="inner")
    frame = _enrich_merged_features(merged)
    elapsed = time.perf_counter() - t0
    logger.info(
        "Preisprognose: Live-Features fertig in %.1fs (Wetter %.1fs, rows=%s).",
        elapsed,
        t_weather,
        0 if frame is None else len(frame),
    )
    return frame


def _feature_cache_key(slots: list[datetime], mode: str) -> tuple[str, str, str]:
    start = min(slots).isoformat()
    end = max(slots).isoformat()
    return (mode, start, end)


def _get_cached_feature_frame(
    key: tuple[str, str, str],
) -> pd.DataFrame | None:
    import time

    entry = _live_feature_cache.get(key)
    if entry is None:
        return None
    stored_at, frame = entry
    if time.time() - stored_at > LIVE_FEATURE_CACHE_TTL_SEC:
        _live_feature_cache.pop(key, None)
        return None
    return frame


def build_live_feature_frame_for_slots(slot_datetimes: list) -> pd.DataFrame | None:
    """EU-Features für OLS-Prognose fehlender Day-Ahead-Slots (ohne AT-Preise)."""
    import time

    from data.market_prices import normalize_price_slot

    if not slot_datetimes:
        return None

    slots = [normalize_price_slot(dt) for dt in slot_datetimes]
    # Unique hour parents for cache/remap (QH slots share parent-hour features).
    hour_slots = sorted({s.replace(minute=0, second=0, microsecond=0) for s in slots})
    use_archive = _archive_covers_slot_range(slot_datetimes)
    mode = "archive" if use_archive else "live_forecast"
    cache_key = _feature_cache_key(hour_slots, mode)
    cached = _get_cached_feature_frame(cache_key)
    if cached is not None:
        return cached

    try:
        frame = (
            _build_archive_feature_frame(hour_slots)
            if use_archive
            else _build_forecast_feature_frame(hour_slots)
        )
        if frame is None or frame.empty:
            return None
        _live_feature_cache[cache_key] = (time.time(), frame)
        return frame
    except (OSError, ValueError, requests.HTTPError, RuntimeError) as exc:
        logger.warning(
            "Preisprognose: EU-Features nicht ladbar (%s, mode=%s) — "
            "Spiegelung als Fallback für fehlende Slots.",
            _feature_load_error_summary(exc),
            mode,
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
        logger.warning(
            "Preisprognose: Modell nicht gefunden (%s) — Fallback Spiegelung.",
            model_path,
        )
        kwargs["missing_price_strategy"] = MISSING_PRICE_STRATEGY_MIRROR
        return kwargs

    kwargs["forecast_model"] = model
    kwargs["forecast_model_path"] = model_path
    feature_frame = build_live_feature_frame_for_slots(target_hours)
    if feature_frame is not None and not feature_frame.empty:
        kwargs["forecast_feature_frame"] = feature_frame
        return kwargs

    kwargs["missing_price_strategy"] = MISSING_PRICE_STRATEGY_MIRROR
    kwargs.pop("forecast_model", None)
    kwargs.pop("forecast_model_path", None)
    return kwargs


def predict_epex_cent_for_features(frame: pd.DataFrame, model: PriceForecastModel) -> list[float]:
    return [float(v) for v in predict_prices(model, frame)]


def build_predicted_slot(
    slot_datetime,
    epex_cent: float,
    *,
    model_path: Path | None = None,
    import_pricing_kwargs: dict | None = None,
) -> dict[str, Any]:
    """Erzeugt einen resolve_market_slots-kompatiblen Preis-Slot."""
    from data.backtesting_prices import import_brutto_cent_for_slots

    pricing = import_pricing_kwargs or {}
    k_act = import_brutto_cent_for_slots(
        [float(epex_cent)],
        [slot_datetime],
        **pricing,
    )[0]
    row: dict[str, Any] = {
        "slot_datetime": slot_datetime,
        "hour": slot_datetime.hour,
        "price_buy": round(float(epex_cent), 4),
        "price_source": PRICE_SOURCE_PREDICTED,
        "k_act": k_act,
    }
    if model_path is not None:
        row["forecast_model_path"] = str(model_path)
    return row


def is_extrapolated_source(price_source: str | None) -> bool:
    """Chart/UI: extrapoliert = gespiegelt oder prognostiziert."""
    return price_source in (PRICE_SOURCE_MIRRORED, PRICE_SOURCE_PREDICTED)
