"""Backtesting: Day-Ahead-Cutoff und Spiegel/Prognose in der grünen Zone."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

import config
from data.market_prices import (
    MAX_MIRROR_LOOKBACK_DAYS,
    normalize_price_slot,
    resolve_market_slots,
)
from data.price_forecast_live import (
    MISSING_PRICE_STRATEGY_FORECAST,
    MISSING_PRICE_STRATEGY_MIRROR,
)
from data.price_forecast_model import (
    PriceForecastModel,
    enrich_model_features,
    load_price_model,
    load_training_dataset,
    resolve_feature_variant,
)

if TYPE_CHECKING:
    from data.edibert_slot_prices import MarketFor

EPEX_DAY_AHEAD_PUBLISH_HOUR = 12
PRICE_STRATEGY_PERFECT = "perfect"
VALID_PRICE_STRATEGIES = (
    PRICE_STRATEGY_PERFECT,
    MISSING_PRICE_STRATEGY_MIRROR,
    MISSING_PRICE_STRATEGY_FORECAST,
)


def parse_price_strategy(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return PRICE_STRATEGY_PERFECT
    strategy = str(raw).strip().lower()
    if strategy not in VALID_PRICE_STRATEGIES:
        raise ValueError(
            f"price_strategy muss einer von {VALID_PRICE_STRATEGIES} sein, nicht {raw!r}."
        )
    return strategy


def last_day_ahead_calendar_date(planning_moment: datetime) -> date:
    """EPEX Day-Ahead für D+1 typisch ab 12:00 am Vortag verfügbar."""
    slot = normalize_price_slot(planning_moment)
    if slot.hour >= EPEX_DAY_AHEAD_PUBLISH_HOUR:
        return slot.date() + timedelta(days=1)
    return slot.date()


def slot_in_market_data_as_of(slot: datetime, planning_moment: datetime) -> bool:
    """Slot im Marktdaten-Index: bekannter Day-Ahead oder Historie für Spiegelung."""
    slot_n = normalize_price_slot(_ensure_planning_tz(slot))
    cutoff = last_day_ahead_calendar_date(planning_moment)
    if slot_n.date() <= cutoff:
        return True
    return slot_n < normalize_price_slot(_ensure_planning_tz(planning_moment))


def _ensure_planning_tz(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        return moment
    from zoneinfo import ZoneInfo

    return moment.replace(tzinfo=ZoneInfo(config.get_planning_timezone()))


def _slot_from_prices_index(ts: pd.Timestamp) -> datetime:
    return normalize_price_slot(_ensure_planning_tz(ts.to_pydatetime()))


def build_market_data_as_of(
    prices_df: pd.DataFrame,
    planning_moment: datetime,
    *,
    not_before: datetime | None = None,
) -> list[dict[str, Any]]:
    """Marktdaten wie zum Planungszeitpunkt (ohne noch unveröffentlichte Day-Ahead-Stunden).

    ``not_before`` (naive Planungszeit) lässt ältere Zeilen weg; die Reihe wird vor der
    Schleife per Index zugeschnitten, damit nicht jeder Anker das ganze Jahr durchläuft.
    """
    cutoff = last_day_ahead_calendar_date(planning_moment)
    index = prices_df.index

    def _bound(moment: datetime) -> pd.Timestamp:
        bound = pd.Timestamp(moment.replace(tzinfo=None))
        if index.tz is None:
            return bound
        return bound.tz_localize(config.get_planning_timezone(), ambiguous=True, nonexistent="shift_forward")

    # Grob vorfiltern (eine Stunde Spielraum je Seite); die genaue Prüfung macht die Schleife.
    mask = index < _bound(datetime.combine(cutoff, datetime.min.time()) + timedelta(days=1, hours=1))
    if not_before is not None:
        mask &= index >= _bound(not_before - timedelta(hours=1))
    window = prices_df.loc[mask, "price_cent_kwh"]
    entries: list[dict[str, Any]] = []
    for ts, price in zip(window.index, window.to_numpy()):
        slot = _slot_from_prices_index(ts)
        if not slot_in_market_data_as_of(slot, planning_moment):
            continue
        entries.append(
            {
                "timestamp": slot,
                "hour": slot.hour,
                "price_buy": round(float(price), 4),
            }
        )
    return entries


def _align_feature_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Index auf naive Planungszeitzone (passend zu Backtesting-Slots)."""
    tz_name = config.get_planning_timezone()
    idx = frame.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    localized = idx.tz_convert(tz_name).tz_localize(None)
    aligned = frame.copy()
    aligned.index = localized
    return aligned


def load_backtesting_feature_frame(dataset_path: Path) -> pd.DataFrame:
    peek = load_training_dataset(dataset_path, feature_variant="base")
    variant = resolve_feature_variant(peek)
    frame = load_training_dataset(dataset_path, feature_variant=variant)
    return enrich_model_features(_align_feature_index(frame))


def load_backtesting_forecast_model(model_path: Path) -> PriceForecastModel:
    if not model_path.exists():
        raise FileNotFoundError(f"Preismodell nicht gefunden: {model_path}")
    return load_price_model(model_path)


@dataclass(frozen=True)
class BacktestingPriceContext:
    strategy: str
    planning_moment: datetime
    feature_frame: pd.DataFrame | None = None
    forecast_model: PriceForecastModel | None = None
    forecast_model_path: Path | None = None


@dataclass(frozen=True)
class BacktestingPriceResources:
    """Geladene Ressourcen für alle Anker eines Backtesting-Laufs."""

    strategy: str
    feature_frame: pd.DataFrame | None = None
    forecast_model: PriceForecastModel | None = None
    forecast_model_path: Path | None = None

    def at_planning_moment(self, planning_moment: datetime) -> BacktestingPriceContext:
        return BacktestingPriceContext(
            strategy=self.strategy,
            planning_moment=planning_moment,
            feature_frame=self.feature_frame,
            forecast_model=self.forecast_model,
            forecast_model_path=self.forecast_model_path,
        )


def load_price_resources(
    strategy: str,
    *,
    feature_dataset_path: Path | None = None,
    forecast_model_path: Path | None = None,
) -> BacktestingPriceResources | None:
    parsed = parse_price_strategy(strategy)
    if parsed == PRICE_STRATEGY_PERFECT:
        return None
    if parsed == MISSING_PRICE_STRATEGY_FORECAST:
        if feature_dataset_path is None or forecast_model_path is None:
            raise ValueError(
                "price_strategy=forecast erfordert feature_dataset_path und forecast_model_path."
            )
        return BacktestingPriceResources(
            strategy=parsed,
            feature_frame=load_backtesting_feature_frame(feature_dataset_path),
            forecast_model=load_backtesting_forecast_model(forecast_model_path),
            forecast_model_path=forecast_model_path,
        )
    return BacktestingPriceResources(strategy=MISSING_PRICE_STRATEGY_MIRROR)


def build_price_context(
    strategy: str,
    planning_moment: datetime,
    *,
    feature_dataset_path: Path | None = None,
    forecast_model_path: Path | None = None,
) -> BacktestingPriceContext | None:
    parsed = parse_price_strategy(strategy)
    if parsed == PRICE_STRATEGY_PERFECT:
        return None
    if parsed == MISSING_PRICE_STRATEGY_FORECAST:
        if feature_dataset_path is None or forecast_model_path is None:
            raise ValueError(
                "price_strategy=forecast erfordert feature_dataset_path und forecast_model_path."
            )
        return BacktestingPriceContext(
            strategy=parsed,
            planning_moment=planning_moment,
            feature_frame=load_backtesting_feature_frame(feature_dataset_path),
            forecast_model=load_backtesting_forecast_model(forecast_model_path),
            forecast_model_path=forecast_model_path,
        )
    return BacktestingPriceContext(
        strategy=MISSING_PRICE_STRATEGY_MIRROR,
        planning_moment=planning_moment,
    )


def _target_hour(slot: datetime) -> datetime:
    return normalize_price_slot(_ensure_planning_tz(slot))


def resolve_backtesting_slot_prices(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
    ctx: BacktestingPriceContext,
) -> list[dict[str, Any]]:
    """Preis-Slots mit Day-Ahead-Cutoff; fehlende Stunden per Spiegelung oder Prognose."""
    target_hours = [_target_hour(slot) for slot in slot_datetimes]
    # Mirror (7 Tage) und Live-Bias (48 h) lesen nie weiter zurück als 8 Tage vor dem ersten Slot.
    not_before = min(target_hours) - timedelta(days=MAX_MIRROR_LOOKBACK_DAYS + 1)
    market_data = build_market_data_as_of(
        prices_df, ctx.planning_moment, not_before=not_before
    )
    resolved = resolve_market_slots(
        market_data,
        target_hours,
        missing_price_strategy=ctx.strategy,
        forecast_model=ctx.forecast_model,
        forecast_feature_frame=ctx.feature_frame,
        forecast_model_path=ctx.forecast_model_path,
        # As live (default 48 h, ±12 ct), but the lookback features come from the training
        # CSV: the SE must not fetch EU power from Energy-Charts per window.
        live_bias_enabled=ctx.strategy == MISSING_PRICE_STRATEGY_FORECAST,
        live_bias_feature_frame=ctx.feature_frame,
    )
    for row, slot in zip(resolved, slot_datetimes):
        row["slot_datetime"] = slot
    return resolved


def pricing_kwargs_from_resolved(resolved: dict | None) -> dict:
    """Pricing kwargs (Edibert reference) of a resolved runtime scenario (live + backtesting)."""
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY

    if not resolved or resolved.get(EDIBERT_PRICING_KEY) is None:
        return {}
    return {"edibert_pricing": resolved[EDIBERT_PRICING_KEY]}


def import_brutto_cent_for_slots(
    epex_values: list[float],
    slot_datetimes: list[datetime],
    *,
    edibert_pricing: dict | None = None,
    market_for: MarketFor | None = None,
) -> list[float]:
    """EPEX Cent/kWh → Bezugspreis je Slot aus dem Bezugstarif (Edibert).

    ``market_for`` liefert Börsenpreise für Viertelstunden außerhalb der Liste, die ein
    stündlich abgerechneter Tarif für das Stundenmittel braucht (Edibert P3b, D1).
    """
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, import_cents, require_pricing_reference

    ref = require_pricing_reference(
        {EDIBERT_PRICING_KEY: edibert_pricing}, where="Bezugspreis je Slot"
    )
    return import_cents(slot_datetimes, epex_values, ref, market_for=market_for)


def enrich_slots_import_prices(
    slots: list[dict[str, Any]],
    slot_datetimes: list[datetime],
    *,
    edibert_pricing: dict | None = None,
    market_for: MarketFor | None = None,
) -> None:
    """Setzt k_act in resolve_market_slots-Ergebnissen aus dem Bezugstarif."""
    epex_values = [float(slot["price_buy"]) for slot in slots]
    brutto = import_brutto_cent_for_slots(
        epex_values,
        slot_datetimes,
        edibert_pricing=edibert_pricing,
        market_for=market_for,
    )
    for slot, price in zip(slots, brutto):
        slot["k_act"] = price


def market_for_prices(
    prices_df: pd.DataFrame,
    ctx: BacktestingPriceContext | None,
    *,
    planning_moment: datetime | None = None,
) -> MarketFor:
    """Börsenpreise für zusätzliche Viertelstunden, genauso beschafft wie die des Horizonts."""

    def _market(slots: list[datetime]) -> list[float | None]:
        naive = [slot.replace(tzinfo=None) for slot in slots]
        if ctx is None:
            from data.market_prices import epex_prices_for_slots

            return list(epex_prices_for_slots(prices_df, naive))
        moment = planning_moment if planning_moment is not None else ctx.planning_moment
        price_ctx = BacktestingPriceContext(
            strategy=ctx.strategy,
            planning_moment=moment,
            feature_frame=ctx.feature_frame,
            forecast_model=ctx.forecast_model,
            forecast_model_path=ctx.forecast_model_path,
        )
        return [float(row["price_buy"]) for row in resolve_backtesting_slot_prices(prices_df, naive, price_ctx)]

    return _market


def matrix_prices_from_context(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
    ctx: BacktestingPriceContext | None,
    *,
    planning_moment: datetime | None = None,
    edibert_pricing: dict | None = None,
) -> tuple[list[float], list[float], list[str]]:
    """EPEX- und Brutto-Preise je Slot; bei ctx=None Perfect-Foresight aus CSV."""
    market_for = market_for_prices(prices_df, ctx, planning_moment=planning_moment)

    def _brutto_list(epex_values: list[float]) -> list[float]:
        return import_brutto_cent_for_slots(
            epex_values,
            slot_datetimes,
            edibert_pricing=edibert_pricing,
            market_for=market_for,
        )

    if ctx is None:
        from data.market_prices import epex_prices_for_slots

        epex = epex_prices_for_slots(prices_df, slot_datetimes)
        brutto = _brutto_list(epex)
        return epex, brutto, ["day_ahead"] * len(epex)

    moment = planning_moment if planning_moment is not None else ctx.planning_moment
    price_ctx = BacktestingPriceContext(
        strategy=ctx.strategy,
        planning_moment=moment,
        feature_frame=ctx.feature_frame,
        forecast_model=ctx.forecast_model,
        forecast_model_path=ctx.forecast_model_path,
    )
    slots = resolve_backtesting_slot_prices(prices_df, slot_datetimes, price_ctx)
    epex = [float(s["price_buy"]) for s in slots]
    brutto = _brutto_list(epex)
    sources = [str(s.get("price_source", "day_ahead")) for s in slots]
    return epex, brutto, sources
