"""Live-Vorbereitung: Preisprognose für fehlende Day-Ahead-Slots (Phase 3)."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from data.market_prices import PRICE_SOURCE_DAY_AHEAD, PRICE_SOURCE_MIRRORED
from data.price_forecast_model import (
    PriceForecastModel,
    load_price_model,
    predict_prices,
)

from data.market_prices import PRICE_SOURCE_PREDICTED
from runtime_store.cycle_duration_stats import (
    EVENT_PRICE_FEATURE_REFRESH,
    record_event as record_cycle_event,
)
from runtime_store.persist_paths import resolve_runtime_prefixed_path
from runtime_store.planning_clock import planning_now

MISSING_PRICE_STRATEGY_MIRROR = "mirror"
MISSING_PRICE_STRATEGY_FORECAST = "forecast"
DEFAULT_LIVE_BIAS_LOOKBACK_HOURS = 48
DEFAULT_LIVE_BIAS_CAP_CENT = 12.0
MIN_LIVE_BIAS_SAMPLES = 6
# Seam: the first predicted slot starts at the residual of the last known hours, which decays
# linearly into the rolling bias (backtest 2026-03..11 in docs/dev/price-forecast-seam.md).
DEFAULT_LIVE_BIAS_SEAM_HOURS = 2
DEFAULT_LIVE_BIAS_SEAM_DECAY_HOURS = 8.0
DEFAULT_MODEL_PATH = Path("share/data/price_model_coefficients.json")
LEGACY_MODEL_PATH = Path("data/cache/price_model_coefficients.json")
LIVE_FEATURE_CACHE_TTL_SEC = 45 * 60
# After a failed EU feature load the network is not asked again for this long, so an
# unreachable Energy-Charts costs one timeout per hour instead of one per cycle.
LIVE_FEATURE_FAILURE_BACKOFF_SEC = 60 * 60

logger = logging.getLogger(__name__)

_model_fallback_warned = False
# Network inputs of the EU features, keyed by (kind, start date, end date): the
# planning window moves every hour, its calendar days do not.
_feature_input_cache: dict[tuple[str, date, date], tuple[float, pd.DataFrame]] = {}
# Reference day -> (EU power, stood-in countries, monotonic fetch time).
_power_day_cache: dict[date, tuple[pd.DataFrame, tuple[str, ...], float]] = {}
# Feature frame attribute: countries whose power was stood in by their share.
EU_POWER_STAND_IN_ATTR = "eu_power_stand_in"
# Feature mode ("archive" / "live_forecast") -> monotonic time until which a failed
# load is not retried.
_feature_failure_until: dict[str, float] = {}
_feature_failure_clock = time.monotonic


def _feature_load_error_summary(exc: BaseException) -> str:
    """Kurzbeschreibung für Logs (ohne volle Request-URL)."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        # Status only — request exception strings often embed the full URL.
        return f"HTTP {exc.response.status_code}"
    detail = type(exc).__name__
    msg = str(exc).strip()
    if not msg:
        return detail
    # Drop query strings that may appear in request-related messages.
    compact = msg.split("?")[0]
    if len(compact) > 180:
        compact = compact[:177] + "..."
    return f"{detail}: {compact}"


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


def get_live_bias_enabled() -> bool:
    """Rolling EPEX residual on predicted slots (default on)."""
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get(
        "market_prices"
    )
    if not isinstance(block, dict):
        return True
    if "live_bias_enabled" not in block:
        return True
    return bool(block.get("live_bias_enabled"))


def get_live_bias_lookback_hours() -> int:
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get(
        "market_prices"
    )
    raw = (
        block.get("live_bias_lookback_hours", DEFAULT_LIVE_BIAS_LOOKBACK_HOURS)
        if isinstance(block, dict)
        else DEFAULT_LIVE_BIAS_LOOKBACK_HOURS
    )
    hours = int(raw)
    if hours < 1:
        raise ValueError(
            "market_prices.live_bias_lookback_hours muss >= 1 sein."
        )
    return hours


def get_live_bias_cap_cent_kwh() -> float:
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get(
        "market_prices"
    )
    raw = (
        block.get("live_bias_cap_cent_kwh", DEFAULT_LIVE_BIAS_CAP_CENT)
        if isinstance(block, dict)
        else DEFAULT_LIVE_BIAS_CAP_CENT
    )
    cap = float(raw)
    if cap <= 0:
        raise ValueError("market_prices.live_bias_cap_cent_kwh muss > 0 sein.")
    return cap


def _market_prices_block() -> dict:
    import config

    block = config.Config._read_json_dict(str(config.CONFIG_JSON_PATH)).get("market_prices")
    return block if isinstance(block, dict) else {}


def get_live_bias_seam_hours() -> int:
    """Known hours before the first predicted slot whose residual starts the forecast."""
    raw = _market_prices_block().get("live_bias_seam_hours", DEFAULT_LIVE_BIAS_SEAM_HOURS)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("market_prices.live_bias_seam_hours muss eine ganze Zahl >= 1 sein.")
    return raw


def get_live_bias_seam_decay_hours() -> float:
    """Hours over which the seam residual decays into the rolling bias; 0 = no seam."""
    import math

    raw = _market_prices_block().get(
        "live_bias_seam_decay_hours", DEFAULT_LIVE_BIAS_SEAM_DECAY_HOURS
    )
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
        raise ValueError("market_prices.live_bias_seam_decay_hours muss eine Zahl >= 0 sein.")
    return float(raw)


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
    """Letzter Kalendertag mit vollständigen Open-Meteo/Energy-Charts-Archivdaten.

    Uses the wall clock (and a frozen test clock), not :func:`planning_now`.
    Offline replay freezes the planning clock to the cycle timestamp; the archive
    cut-off is a property of available data at run time, not of that cycle.
    """
    import sys
    from datetime import datetime
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


def _cached_eu_power_day(ref_day: date) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Archive EU power for one calendar day and its stood-in countries (process-local cache).

    A country Energy-Charts has no data for is stood in by its share
    (``fetch_eu_power_hourly_with_stand_in``). A complete day is cached for good; a day
    with a stand-in only for ``LIVE_FEATURE_FAILURE_BACKOFF_SEC``, so data published later
    (a country that only lags) replaces the estimate without asking in every cycle.
    """
    from data.eu_market_features import fetch_eu_power_hourly_with_stand_in, load_country_shares

    cached = _power_day_cache.get(ref_day)
    if cached is not None:
        frame, stand_in, fetched_at = cached
        if not stand_in or _feature_failure_clock() - fetched_at < LIVE_FEATURE_FAILURE_BACKOFF_SEC:
            return frame, stand_in
    logger.info(
        "Preisprognose: lade EU-Leistungs-Archiv für %s (gecacht)…",
        ref_day.isoformat(),
    )
    frame, stand_in = fetch_eu_power_hourly_with_stand_in(
        ref_day, ref_day + timedelta(days=1), load_country_shares()
    )
    _power_day_cache[ref_day] = (frame, stand_in, _feature_failure_clock())
    return frame, stand_in


def _cached_feature_input(kind: str, start: date, end: date, fetch) -> pd.DataFrame:
    """Network input for ``[start, end)`` from the process cache, else ``fetch()``.

    Fresh for ``LIVE_FEATURE_CACHE_TTL_SEC`` (refresh-ahead aware, see
    ``runtime_store.planning_clock.cache_valid_until``). Only a real fetch is
    reported as ``price_feature_refresh``.
    """
    import time

    from runtime_store.planning_clock import cache_entry_fresh

    key = (kind, start, end)
    entry = _feature_input_cache.get(key)
    if entry is not None and cache_entry_fresh(entry[0], LIVE_FEATURE_CACHE_TTL_SEC):
        return entry[1]
    record_cycle_event(EVENT_PRICE_FEATURE_REFRESH)
    value = fetch()
    now = time.time()
    for stale in [k for k, (at, _v) in _feature_input_cache.items() if now - at >= LIVE_FEATURE_CACHE_TTL_SEC]:
        _feature_input_cache.pop(stale, None)
    _feature_input_cache[key] = (now, value)
    return value


def _build_archive_feature_frame(slots: list[datetime]) -> pd.DataFrame | None:
    from data.eu_market_features import fetch_eu_power_hourly, fetch_eu_weather_hourly

    start = min(slot.date() for slot in slots)
    end = max(slot.date() for slot in slots) + timedelta(days=1)
    weather = _cached_feature_input(
        "archive_weather", start, end, lambda: fetch_eu_weather_hourly(start, end)
    )
    power = _cached_feature_input(
        "archive_power", start, end, lambda: fetch_eu_power_hourly(start, end)
    )
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
    logger.debug(
        "Preisprognose: Live-Features %s..%s (%d Stunden-Slots)…",
        start.isoformat(),
        (end - timedelta(days=1)).isoformat(),
        len(slots),
    )
    weather = _cached_feature_input(
        "forecast_weather", start, end, lambda: fetch_eu_weather_forecast_hourly(start, end)
    )
    t_weather = time.perf_counter() - t0
    ref_day = _archive_latest_complete_day()
    power_ref, stand_in = _cached_eu_power_day(ref_day)
    power = remap_power_by_hour_of_day(power_ref, slots)
    merged = power.join(weather, how="inner")
    frame = _enrich_merged_features(merged)
    if frame is not None and stand_in:
        frame.attrs[EU_POWER_STAND_IN_ATTR] = stand_in
    elapsed = time.perf_counter() - t0
    # INFO only when it took noticeable time (network); cached builds are routine.
    logger.log(
        logging.INFO if elapsed >= 1.0 else logging.DEBUG,
        "Preisprognose: Live-Features %s..%s fertig in %.1fs (Wetter %.1fs, rows=%s).",
        start.isoformat(),
        (end - timedelta(days=1)).isoformat(),
        elapsed,
        t_weather,
        0 if frame is None else len(frame),
    )
    return frame


def build_live_feature_frame_for_slots(slot_datetimes: list) -> pd.DataFrame | None:
    """EU-Features für OLS-Prognose fehlender Day-Ahead-Slots (ohne AT-Preise)."""
    from data.market_prices import normalize_price_slot

    if not slot_datetimes:
        return None

    slots = [normalize_price_slot(dt) for dt in slot_datetimes]
    # Unique hour parents for cache/remap (QH slots share parent-hour features).
    hour_slots = sorted({s.replace(minute=0, second=0, microsecond=0) for s in slots})
    use_archive = _archive_covers_slot_range(slot_datetimes)
    mode = "archive" if use_archive else "live_forecast"
    retry_at = _feature_failure_until.get(mode)
    if retry_at is not None and _feature_failure_clock() < retry_at:
        logger.debug(
            "Preisprognose: EU-Features (mode=%s) nach Fehler pausiert, nächster Versuch in %.0f min.",
            mode,
            (retry_at - _feature_failure_clock()) / 60,
        )
        return None
    try:
        frame = (
            _build_archive_feature_frame(hour_slots)
            if use_archive
            else _build_forecast_feature_frame(hour_slots)
        )
        _feature_failure_until.pop(mode, None)
        if frame is None or frame.empty:
            return None
        return frame
    except (OSError, ValueError, requests.HTTPError, RuntimeError) as exc:
        _feature_failure_until[mode] = (
            _feature_failure_clock() + LIVE_FEATURE_FAILURE_BACKOFF_SEC
        )
        logger.warning(
            "Preisprognose: EU-Features nicht ladbar (%s, mode=%s) — "
            "Spiegelung als Fallback für fehlende Slots; nächster Versuch in %d min.",
            _feature_load_error_summary(exc),
            mode,
            LIVE_FEATURE_FAILURE_BACKOFF_SEC // 60,
        )
        return None


def compute_rolling_epex_bias_cent(
    day_ahead_by_slot: dict[datetime, float],
    *,
    forecast_model: PriceForecastModel,
    reference_slot: datetime,
    lookback_hours: int,
    cap_cent_kwh: float = DEFAULT_LIVE_BIAS_CAP_CENT,
    min_samples: int = MIN_LIVE_BIAS_SAMPLES,
    feature_frame: pd.DataFrame | None = None,
) -> tuple[float | None, int]:
    """Mean (actual − model) over recent Day-Ahead hours; capped.

    ``feature_frame`` holds the lookback features (SE: training CSV); without it they are
    fetched live (``build_live_feature_frame_for_slots``).

    The window is the ``lookback_hours`` clock hours before ``reference_slot``; an hour's actual
    price is the mean of its known quarter-hours.

    Returns (bias_cent_or_None, sample_count).
    """
    lookback_slots = lookback_hour_slots(reference_slot, lookback_hours)
    if feature_frame is None:
        feature_frame = build_live_feature_frame_for_slots(lookback_slots)
    if feature_frame is None or feature_frame.empty:
        logger.warning(
            "Preisprognose: live bias — keine Features für Lookback."
        )
        return None, 0

    residuals = hourly_residuals_cent(
        day_ahead_by_slot, forecast_model=forecast_model, hour_slots=lookback_slots, feature_frame=feature_frame
    )

    if len(residuals) < min_samples:
        logger.warning(
            "Preisprognose: live bias — zu wenige Samples (%d < %d).",
            len(residuals),
            min_samples,
        )
        return None, len(residuals)

    bias = sum(residuals) / len(residuals)
    capped = max(-cap_cent_kwh, min(cap_cent_kwh, bias))
    logger.info(
        "Preisprognose: live bias %.3f Cent/kWh (raw %.3f, n=%d, cap=±%.1f).",
        capped,
        bias,
        len(residuals),
        cap_cent_kwh,
    )
    return capped, len(residuals)


def lookback_hour_slots(reference_slot: datetime, hours: int) -> list[datetime]:
    """The ``hours`` clock hours before ``reference_slot`` (newest first), as slot keys."""
    from data.market_prices import normalize_price_slot
    from optimizer.slot_duration import fixed_offset_local, floor_to_hour_slot, slot_zone

    ref = floor_to_hour_slot(normalize_price_slot(reference_slot))
    zone = slot_zone(ref)
    return [fixed_offset_local(ref - timedelta(hours=back), zone) for back in range(1, hours + 1)]


def _hour_actual_cent(day_ahead_by_slot: dict[datetime, float], hour_slot: datetime) -> float | None:
    """Mean of the known quarter-hours of ``hour_slot`` (an hourly price counts as its hour)."""
    prices = [
        day_ahead_by_slot[slot]
        for slot in (hour_slot + timedelta(minutes=minutes) for minutes in (0, 15, 30, 45))
        if slot in day_ahead_by_slot
    ]
    return sum(prices) / len(prices) if prices else None


def hourly_residuals_cent(
    day_ahead_by_slot: dict[datetime, float],
    *,
    forecast_model: PriceForecastModel,
    hour_slots: list[datetime],
    feature_frame: pd.DataFrame,
) -> list[float]:
    """Actual − OLS per hour of ``hour_slots`` that has a known price and a feature row."""
    from optimizer.slot_duration import floor_to_hour_slot

    residuals: list[float] = []
    for slot in hour_slots:
        actual = _hour_actual_cent(day_ahead_by_slot, floor_to_hour_slot(slot))
        if actual is None:
            continue
        lookup = slot.replace(tzinfo=None) if feature_frame.index.tz is None else slot
        if lookup not in feature_frame.index:
            parent = floor_to_hour_slot(lookup)
            if parent not in feature_frame.index:
                continue
            lookup = parent
        predicted = float(predict_prices(forecast_model, feature_frame.loc[[lookup]])[0])
        residuals.append(float(actual) - predicted)
    return residuals


def compute_seam_anchor_cent(
    day_ahead_by_slot: dict[datetime, float],
    *,
    forecast_model: PriceForecastModel,
    seam_slot: datetime,
    seam_hours: int,
    cap_cent_kwh: float,
    feature_frame: pd.DataFrame,
) -> float | None:
    """Mean residual of the ``seam_hours`` known hours right before the first predicted slot.

    None (logged) when one of these hours has no price or no feature row: the forecast then
    uses the rolling bias alone.
    """
    residuals = hourly_residuals_cent(
        day_ahead_by_slot,
        forecast_model=forecast_model,
        hour_slots=lookback_hour_slots(seam_slot, seam_hours),
        feature_frame=feature_frame,
    )
    if len(residuals) < seam_hours:
        logger.warning(
            "Preisprognose: Anschluss an %s ohne Werte (%d von %d Stunden) — nur live bias.",
            seam_slot,
            len(residuals),
            seam_hours,
        )
        return None
    anchor = sum(residuals) / len(residuals)
    return max(-cap_cent_kwh, min(cap_cent_kwh, anchor))


def live_lookback_feature_frame(
    lookback_slots: list[datetime],
    *,
    planning_start: datetime,
    forecast_feature_frame: pd.DataFrame | None,
) -> pd.DataFrame | None:
    """Features for a bias window that may reach past the planning start.

    Hours before ``planning_start`` come from the live fetch (archive or forecast, as before);
    hours from ``planning_start`` on are rows of the horizon's own ``forecast_feature_frame``,
    which wins on overlap. A naive and an aware index are aligned on naive planning time; two
    aware indexes stay aware (the repeated autumn hour keeps both rows). A failed fetch
    of the past hours gives None (no bias, logged), never a window shrunk to the horizon.
    """
    from optimizer.slot_duration import floor_to_hour_slot

    start_hour = floor_to_hour_slot(planning_start)
    past = [slot for slot in lookback_slots if slot < start_hour]
    frames: list[pd.DataFrame] = []
    if forecast_feature_frame is not None and not forecast_feature_frame.empty:
        frames.append(forecast_feature_frame)
    if past:
        past_frame = build_live_feature_frame_for_slots(past)
        if past_frame is None or past_frame.empty:
            logger.warning(
                "Preisprognose: live bias — keine Features für die %d Lookback-Stunden vor %s.",
                len(past),
                start_hour,
            )
            return None
        frames.append(past_frame)
    if not frames:
        return None
    if len({frame.index.tz is None for frame in frames}) > 1:
        # Mixed naive / aware: align on naive planning time (the live fetch is naive).
        frames = [_naive_planning_index(frame) for frame in frames]
    merged = pd.concat(frames)
    return merged[~merged.index.duplicated(keep="first")].sort_index()


def _naive_planning_index(frame: pd.DataFrame) -> pd.DataFrame:
    """``frame`` with a naive planning-timezone index (an aware index is converted)."""
    if frame.index.tz is None:
        return frame
    import config

    out = frame.copy()
    out.index = frame.index.tz_convert(config.get_planning_timezone()).tz_localize(None)
    return out


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
        stand_in = feature_frame.attrs.get(EU_POWER_STAND_IN_ATTR)
        if stand_in:
            kwargs["eu_power_stand_in"] = tuple(stand_in)
        kwargs["live_bias_enabled"] = get_live_bias_enabled()
        if kwargs["live_bias_enabled"]:
            kwargs["live_bias_lookback_hours"] = get_live_bias_lookback_hours()
            kwargs["live_bias_cap_cent_kwh"] = get_live_bias_cap_cent_kwh()
            kwargs["live_bias_seam_hours"] = get_live_bias_seam_hours()
            kwargs["live_bias_seam_decay_hours"] = get_live_bias_seam_decay_hours()
        return kwargs

    kwargs["missing_price_strategy"] = MISSING_PRICE_STRATEGY_MIRROR
    kwargs.pop("forecast_model", None)
    kwargs.pop("forecast_model_path", None)
    return kwargs


def is_extrapolated_source(price_source: str | None) -> bool:
    """Chart/UI: extrapoliert = gespiegelt oder prognostiziert."""
    return price_source in (PRICE_SOURCE_MIRRORED, PRICE_SOURCE_PREDICTED)
