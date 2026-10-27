"""Earnie's OLS price model as an Edibert forecaster (Edibert P5).

``OlsForecaster`` implements :class:`edibert.api.Forecaster`: Earnie hands the object in directly,
no key involved (the key only guards Edibert plug-ins loaded through entry points). It is pure: the
feature frame and the live bias are computed by the caller (``data.price_forecast_live``,
``data.backtesting_prices``) and passed in. Slots without a feature row are left out, never
guessed; the caller fills them with Edibert's mirror.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from data.price_forecast_model import PriceForecastModel, predict_prices
from optimizer.slot_duration import floor_to_hour_slot, normalize_quarter_hour_slot

METHOD_OLS = "ols"
SLOT = timedelta(minutes=15)


class OlsForecaster:
    """EPEX cent/kWh per 15-minute slot from the OLS model, plus an optional live bias.

    ``feature_frame`` is indexed by planning time (naive or aware), hourly or per quarter-hour; a
    quarter-hour without its own row takes the row of its clock hour.
    """

    def __init__(
        self,
        model: PriceForecastModel,
        feature_frame: pd.DataFrame,
        *,
        tz: ZoneInfo,
        bias_cent: float | None = None,
    ) -> None:
        self.model = model
        self.feature_frame = feature_frame
        self.tz = tz
        self.bias_cent = bias_cent

    def forecast(self, known: Mapping[datetime, float], start: datetime, end: datetime) -> dict[datetime, float]:
        """Prices for the UTC slots of ``[start, end)``; ``known`` is not used (the bias comes from the caller)."""
        result: dict[datetime, float] = {}
        slot = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        while slot < end_utc:
            epex = self._predict(slot)
            if epex is not None:
                result[slot] = epex if self.bias_cent is None else float(epex) + float(self.bias_cent)
            slot += SLOT
        return result

    def _predict(self, slot_utc: datetime) -> float | None:
        key = normalize_quarter_hour_slot(slot_utc.astimezone(self.tz))
        index = self.feature_frame.index
        lookup = key.replace(tzinfo=None) if index.tz is None else key
        if lookup not in index:
            lookup = floor_to_hour_slot(lookup)
            if lookup not in index:
                return None
        return float(predict_prices(self.model, self.feature_frame.loc[[lookup]])[0])
