"""Day-Ahead-Preise für das rollierende 24h-Fenster inkl. Spiegel-Extrapolation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from edibert import api

import config
from data.ols_forecaster import METHOD_OLS, OlsForecaster

PRICE_SOURCE_DAY_AHEAD = "day_ahead"
PRICE_SOURCE_MIRRORED = "mirrored"
PRICE_SOURCE_PREDICTED = "predicted"
MAX_MIRROR_LOOKBACK_DAYS = 7  # as far back as Edibert's MirrorForecaster looks
MAX_FORECAST_HOURS = 72  # as Edibert's publisher; edibert.api does not export it
_SLOT = timedelta(minutes=15)
MISSING_PRICE_STRATEGY_MIRROR = "mirror"
MISSING_PRICE_STRATEGY_FORECAST = "forecast"
_PRICE_SOURCE_BY_METHOD = {
    api.METHOD_EXACT: PRICE_SOURCE_DAY_AHEAD,
    api.METHOD_MIRROR: PRICE_SOURCE_MIRRORED,
    METHOD_OLS: PRICE_SOURCE_PREDICTED,
}


def normalize_price_slot(dt: datetime) -> datetime:
    """Quarter-hour slot in planning timezone (config: runtime_settings.timezone_name)."""
    from zoneinfo import ZoneInfo

    from optimizer.slot_duration import normalize_quarter_hour_slot

    tz = ZoneInfo(config.get_planning_timezone())
    if dt.tzinfo is None:
        aligned = dt.replace(tzinfo=tz)
    else:
        aligned = dt.astimezone(tz)
    return normalize_quarter_hour_slot(aligned)


def index_market_data_by_slot(market_data: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    """Index raw market data by quarter-hour slot (mean on true duplicates)."""
    buckets: dict[datetime, list[float]] = {}
    for item in market_data:
        ts = item.get("timestamp")
        if ts is None:
            continue
        slot = normalize_price_slot(ts)
        try:
            price = float(item["price_buy"])
        except (KeyError, TypeError, ValueError):
            continue
        buckets.setdefault(slot, []).append(price)

    indexed: dict[datetime, dict[str, Any]] = {}
    for slot, prices in buckets.items():
        epex = sum(prices) / len(prices)
        indexed[slot] = {
            "timestamp": slot,
            "hour": slot.hour,
            "price_buy": round(epex, 4),
        }
    return indexed


def price_source_for_method(method: str) -> str:
    """Slot label (``price_source``) for an Edibert price method; an unknown method is an error."""
    try:
        return _PRICE_SOURCE_BY_METHOD[method]
    except KeyError:
        raise ValueError(f"Unbekannte Preismethode {method!r}.") from None


def _known_quarter_hours(
    by_slot: dict[datetime, dict[str, Any]],
) -> dict[datetime, float]:
    """Known prices per quarter-hour (UTC keys); an hourly sample fills its missing quarter-hours."""
    from optimizer.slot_duration import floor_to_hour_slot

    known = {slot: float(row["price_buy"]) for slot, row in by_slot.items()}
    for slot, price in list(known.items()):
        if floor_to_hour_slot(slot) != slot:
            continue
        for minutes in (15, 30, 45):
            known.setdefault(slot + timedelta(minutes=minutes), price)
    return {slot.astimezone(UTC): price for slot, price in known.items()}


def _append_mirrored_slot(
    resolved: list[dict[str, Any]],
    slot: datetime,
    epex: float,
) -> None:
    resolved.append(
        {
            "slot_datetime": slot,
            "hour": slot.hour,
            "price_buy": epex,
            "price_source": price_source_for_method(api.METHOD_MIRROR),
        }
    )


def _append_predicted_slot(
    resolved: list[dict[str, Any]],
    slot: datetime,
    epex_cent: float,
    *,
    forecast_model_path: Path | None = None,
    eu_power_live_source: str | None = None,
    live_bias_cent_kwh: float | None = None,
) -> None:
    row: dict[str, Any] = {
        "slot_datetime": slot,
        "hour": slot.hour,
        "price_buy": round(float(epex_cent), 4),
        "price_source": price_source_for_method(METHOD_OLS),
    }
    if forecast_model_path is not None:
        row["forecast_model_path"] = str(forecast_model_path)
    if eu_power_live_source is not None:
        row["eu_power_live_source"] = eu_power_live_source
    if live_bias_cent_kwh is not None:
        row["live_bias_cent_kwh"] = float(live_bias_cent_kwh)
    resolved.append(row)


def _day_ahead_epex_by_slot(
    by_slot: dict[datetime, dict[str, Any]],
) -> dict[datetime, float]:
    return {slot: float(row["price_buy"]) for slot, row in by_slot.items()}


def _resolve_live_bias_cent(
    by_slot: dict[datetime, dict[str, Any]],
    target_hours: list[datetime],
    *,
    forecast_model: Any,
    live_bias_enabled: bool,
    live_bias_lookback_hours: int,
    live_bias_cap_cent_kwh: float,
) -> float | None:
    if not live_bias_enabled or forecast_model is None or not target_hours:
        return None
    from data.price_forecast_live import compute_rolling_epex_bias_cent

    ref = min(normalize_price_slot(dt) for dt in target_hours)
    bias, _n = compute_rolling_epex_bias_cent(
        _day_ahead_epex_by_slot(by_slot),
        forecast_model=forecast_model,
        reference_slot=ref,
        lookback_hours=live_bias_lookback_hours,
        cap_cent_kwh=live_bias_cap_cent_kwh,
    )
    return bias


def _check_forecast_span(start: datetime, end: datetime) -> None:
    if end - start > timedelta(hours=MAX_FORECAST_HOURS):
        raise ValueError(
            f"Prognosezeitraum {start.astimezone(UTC):%Y-%m-%d %H:%M} bis "
            f"{end.astimezone(UTC):%Y-%m-%d %H:%M} UTC ist länger als {MAX_FORECAST_HOURS} h."
        )


def _forecast_missing_slots(
    missing: list[datetime],
    known: dict[datetime, float],
    tz: ZoneInfo,
    *,
    ols: OlsForecaster | None,
) -> dict[datetime, tuple[float, str]]:
    """Price and method per missing UTC slot: OLS where it has features, else Edibert's mirror."""
    if not missing:
        return {}
    start, end = min(missing), max(missing) + _SLOT
    _check_forecast_span(start, end)
    filled: dict[datetime, tuple[float, str]] = {}
    if ols is not None:
        predicted = ols.forecast(known, start, end)
        filled = {slot: (predicted[slot], METHOD_OLS) for slot in missing if slot in predicted}
    rest = [slot for slot in missing if slot not in filled]
    if not rest:
        return filled
    mirror = api.builtin_forecaster(api.METHOD_MIRROR, tz)
    mirrored = mirror.forecast(known, min(rest), max(rest) + _SLOT)
    for slot in rest:
        if slot not in mirrored:
            local = slot.astimezone(tz)
            raise ValueError(
                f"Kein Day-Ahead-Preis für {local:%Y-%m-%d %H:%M} und keine Spiegelquelle "
                f"innerhalb von {MAX_MIRROR_LOOKBACK_DAYS} Tagen verfügbar. "
                "Abrufzeitraum erweitern oder später erneut versuchen."
            )
        filled[slot] = (float(mirrored[slot]), api.METHOD_MIRROR)
    return filled


def resolve_market_slots(
    market_data: list[dict[str, Any]],
    target_hours: list[datetime],
    *,
    missing_price_strategy: str = MISSING_PRICE_STRATEGY_MIRROR,
    forecast_model: Any | None = None,
    forecast_feature_frame: pd.DataFrame | None = None,
    forecast_model_path: Path | None = None,
    eu_power_live_source: str | None = None,
    live_bias_enabled: bool = True,
    live_bias_lookback_hours: int = 48,
    live_bias_cap_cent_kwh: float = 12.0,
) -> list[dict[str, Any]]:
    """
    Liefert Börsenpreis-Slots (``price_buy``) für target_hours (beliebige Länge >= 1).

    Endkundenpreise (``k_act``) kommen danach für die ganze Liste aus dem Tarif
    (``data.backtesting_prices.enrich_slots_import_prices``, Edibert).

    Fehlende Day-Ahead-Stunden: Spiegelung (Standard, Edibert ``MirrorForecaster``) oder
    OLS-Prognose bei missing_price_strategy='forecast' (``OlsForecaster``, ein Edibert-Forecaster;
    Slots ohne Features: Spiegelung). Stündliche Werte gelten für alle vier Viertelstunden ihrer
    Stunde. Der Prognosezeitraum (erster bis letzter fehlender Slot) ist höchstens
    ``MAX_FORECAST_HOURS`` lang, sonst ``ValueError``.

    Live bias (default on): rolling Day-Ahead−OLS residual on predicted slots,
    capped by ``live_bias_cap_cent_kwh`` (default ±12 Cent/kWh).
    """
    if not target_hours:
        raise ValueError("resolve_market_slots erfordert mindestens eine Zielstunde.")
    if missing_price_strategy not in (
        MISSING_PRICE_STRATEGY_MIRROR,
        MISSING_PRICE_STRATEGY_FORECAST,
    ):
        raise ValueError(
            "missing_price_strategy muss 'mirror' oder 'forecast' sein."
        )

    by_slot = index_market_data_by_slot(market_data)
    live_bias = _resolve_live_bias_cent(
        by_slot,
        target_hours,
        forecast_model=forecast_model,
        live_bias_enabled=live_bias_enabled,
        live_bias_lookback_hours=live_bias_lookback_hours,
        live_bias_cap_cent_kwh=live_bias_cap_cent_kwh,
    )
    known = _known_quarter_hours(by_slot)
    tz = ZoneInfo(config.get_planning_timezone())
    ols = (
        OlsForecaster(forecast_model, forecast_feature_frame, tz=tz, bias_cent=live_bias)
        if missing_price_strategy == MISSING_PRICE_STRATEGY_FORECAST
        and forecast_model is not None
        and forecast_feature_frame is not None
        else None
    )
    slots = [normalize_price_slot(target_dt) for target_dt in target_hours]
    missing = sorted({slot.astimezone(UTC) for slot in slots} - known.keys())
    forecast = _forecast_missing_slots(missing, known, tz, ols=ols)
    resolved: list[dict[str, Any]] = []

    for slot in slots:
        slot_utc = slot.astimezone(UTC)
        epex = known.get(slot_utc)
        if epex is not None:
            resolved.append(
                {
                    "slot_datetime": slot,
                    "hour": slot.hour,
                    "price_buy": epex,
                    "price_source": price_source_for_method(api.METHOD_EXACT),
                }
            )
            continue
        epex, method = forecast[slot_utc]
        if method == METHOD_OLS:
            _append_predicted_slot(
                resolved,
                slot,
                epex,
                forecast_model_path=forecast_model_path,
                eu_power_live_source=eu_power_live_source,
                live_bias_cent_kwh=live_bias,
            )
        else:
            _append_mirrored_slot(resolved, slot, epex)

    return resolved


def resolve_24h_market_slots(
    market_data: list[dict[str, Any]],
    target_hours: list[datetime],
) -> list[dict[str, Any]]:
    """Kompatibilitäts-Wrapper; bevorzugt resolve_market_slots direkt."""
    return resolve_market_slots(market_data, target_hours)


def mirrored_price_share(resolved_slots: list[dict[str, Any]]) -> float:
    """Anteil gespiegelter Preise (0.0–1.0)."""
    if not resolved_slots:
        return 0.0
    mirrored = sum(
        1 for slot in resolved_slots if slot.get("price_source") == PRICE_SOURCE_MIRRORED
    )
    return mirrored / len(resolved_slots)


def epex_prices_for_slots(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
) -> list[float]:
    """EPEX Cent/kWh je Planungs-Slot; native QH kept, hourly series expanded."""
    from optimizer.slot_duration import floor_to_hour_slot

    series = prices_df["price_cent_kwh"]
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("prices_df index must be DatetimeIndex for epex_prices_for_slots.")
    # Drop tz for naive slot_datetimes used in SE; keep aligned lookup keys.
    idx = series.index
    if getattr(idx, "tz", None) is not None:
        series = series.copy()
        series.index = idx.tz_localize(None)

    out: list[float] = []
    for slot in slot_datetimes:
        key = pd.Timestamp(slot).to_pydatetime().replace(tzinfo=None)
        if key in series.index:
            out.append(float(series.loc[key]))
            continue
        parent = floor_to_hour_slot(key)
        if parent in series.index:
            out.append(float(series.loc[parent]))
            continue
        # Nearest prior sample (covers sparse archives), then ffill-like fallback.
        prior = series.loc[:key]
        if len(prior) > 0:
            out.append(float(prior.iloc[-1]))
            continue
        later = series.loc[key:]
        if len(later) > 0:
            out.append(float(later.iloc[0]))
            continue
        out.append(0.0)
    return out
