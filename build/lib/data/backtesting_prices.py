"""Backtesting: Day-Ahead-Cutoff und Spiegel/Prognose in der grünen Zone."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

import config
from data.market_prices import (
    epex_to_brutto_cent,
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
) -> list[dict[str, Any]]:
    """Marktdaten wie zum Planungszeitpunkt (ohne noch unveröffentlichte Day-Ahead-Stunden)."""
    entries: list[dict[str, Any]] = []
    for ts, row in prices_df.iterrows():
        slot = _slot_from_prices_index(ts)
        if not slot_in_market_data_as_of(slot, planning_moment):
            continue
        entries.append(
            {
                "timestamp": slot,
                "hour": slot.hour,
                "price_buy": round(float(row["price_cent_kwh"]), 4),
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
    market_data = build_market_data_as_of(prices_df, ctx.planning_moment)
    target_hours = [_target_hour(slot) for slot in slot_datetimes]
    resolved = resolve_market_slots(
        market_data,
        target_hours,
        missing_price_strategy=ctx.strategy,
        forecast_model=ctx.forecast_model,
        forecast_feature_frame=ctx.feature_frame,
        forecast_model_path=ctx.forecast_model_path,
    )
    for row, slot in zip(resolved, slot_datetimes):
        row["slot_datetime"] = slot
    return resolved


def pricing_kwargs_from_resolved(resolved: dict | None) -> dict:
    """Import-Tarif-Kwargs aus aufgelöstem Runtime-Szenario (Live + Backtesting)."""
    if not resolved:
        return {}
    spec = resolved.get("_import_tariff_spec")
    if spec is None:
        return {}
    kwargs: dict = {"import_tariff_spec": spec}
    override = resolved.get("netzentgelt_cent_kwh")
    if override is not None:
        kwargs["netzentgelt_override"] = float(override)
    return kwargs


def import_brutto_cent_for_slots(
    epex_values: list[float],
    slot_datetimes: list[datetime],
    *,
    import_tariff_spec: dict | None = None,
    netzentgelt_override: float | None = None,
) -> list[float]:
    """EPEX Cent/kWh → Bezugspreis je Slot (Tarif-Spec oder Legacy-Brutto)."""
    from data.tariff_pricing import import_cent_kwh

    if import_tariff_spec is None:
        return [epex_to_brutto_cent(float(p)) for p in epex_values]
    tariff_type = str(import_tariff_spec.get("type", "")).strip().lower()
    if tariff_type == "monthly_table":
        return [
            import_cent_kwh(
                float(p),
                import_tariff_spec,
                netzentgelt_override=netzentgelt_override,
                slot_datetime=slot,
            )
            for p, slot in zip(epex_values, slot_datetimes)
        ]
    return [
        import_cent_kwh(
            float(p),
            import_tariff_spec,
            netzentgelt_override=netzentgelt_override,
        )
        for p in epex_values
    ]


def enrich_slots_import_prices(
    slots: list[dict[str, Any]],
    slot_datetimes: list[datetime],
    *,
    import_tariff_spec: dict | None = None,
    netzentgelt_override: float | None = None,
) -> None:
    """Setzt k_act in resolve_market_slots-Ergebnissen aus Tarif-Spec."""
    epex_values = [float(slot["price_buy"]) for slot in slots]
    brutto = import_brutto_cent_for_slots(
        epex_values,
        slot_datetimes,
        import_tariff_spec=import_tariff_spec,
        netzentgelt_override=netzentgelt_override,
    )
    for slot, price in zip(slots, brutto):
        slot["k_act"] = price


def matrix_prices_from_context(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
    ctx: BacktestingPriceContext | None,
    *,
    planning_moment: datetime | None = None,
    import_tariff_spec: dict | None = None,
    netzentgelt_override: float | None = None,
) -> tuple[list[float], list[float], list[str]]:
    """EPEX- und Brutto-Preise je Slot; bei ctx=None Perfect-Foresight aus CSV."""

    def _brutto_list(epex_values: list[float]) -> list[float]:
        return import_brutto_cent_for_slots(
            epex_values,
            slot_datetimes,
            import_tariff_spec=import_tariff_spec,
            netzentgelt_override=netzentgelt_override,
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
