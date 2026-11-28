"""Earnie's OLS price model as an Edibert forecaster (Edibert P5).

``OlsForecaster`` implements :class:`edibert.api.Forecaster`: Earnie hands the object in directly,
no key involved (the key only guards Edibert plug-ins loaded through entry points). It is pure: the
feature frame and the live bias are computed by the caller (``data.price_forecast_live``,
``data.backtesting_prices``) and passed in. Slots without a feature row are left out, never
guessed; the caller fills them with Edibert's mirror.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from data.price_forecast_model import PriceForecastModel, predict_prices
from optimizer.slot_duration import floor_to_hour_slot, normalize_quarter_hour_slot

METHOD_OLS = "ols"
SLOT = timedelta(minutes=15)


@dataclass(frozen=True)
class SeamAnchor:
    """Offset at the first predicted slot that decays into the rolling bias in hourly steps.

    In the clock hour of ``start`` the offset is ``anchor_cent``; each following clock hour it
    steps linearly towards the bias and reaches it ``decay_hours`` after the start hour (a decay
    under one hour holds the anchor for the start hour, then the bias). All
    quarter-hours of a clock hour share one offset, like the hourly OLS value they are added to.
    """

    start: datetime
    anchor_cent: float
    decay_hours: float

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("SeamAnchor.start muss timezone-aware sein.")
        if self.decay_hours <= 0:
            raise ValueError("SeamAnchor.decay_hours muss > 0 sein.")

    def weight(self, slot: datetime) -> float:
        """Share of the anchor in the offset of ``slot`` (1 in the start hour, 0 after the decay).

        Clock hours are counted in UTC, which matches local clock hours for whole-hour UTC
        offsets (all EPEX bidding zones Earnie uses); a half-hour zone would step mid-hour.
        """
        slot_hour = slot.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        start_hour = self.start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        hours = (slot_hour - start_hour).total_seconds() / 3600.0
        if hours <= 0:
            return 1.0
        return max(0.0, 1.0 - hours / self.decay_hours)


class OlsForecaster:
    """EPEX cent/kWh per 15-minute slot from the OLS model, plus an optional live bias.

    ``feature_frame`` is indexed by planning time (naive or aware), hourly or per quarter-hour; a
    quarter-hour without its own row takes the row of its clock hour. With a ``seam`` the offset
    starts at the seam anchor and decays into ``bias_cent`` (``offset_cent``).
    """

    def __init__(
        self,
        model: PriceForecastModel,
        feature_frame: pd.DataFrame,
        *,
        tz: ZoneInfo,
        bias_cent: float | None = None,
        seam: SeamAnchor | None = None,
    ) -> None:
        if seam is not None and bias_cent is None:
            raise ValueError("Ein Preis-Anschluss (seam) braucht einen live bias.")
        self.model = model
        self.feature_frame = feature_frame
        self.tz = tz
        self.bias_cent = bias_cent
        self.seam = seam

    def offset_cent(self, slot: datetime) -> float | None:
        """Correction added to the model price of ``slot`` (None without a live bias)."""
        if self.bias_cent is None:
            return None
        bias = float(self.bias_cent)
        if self.seam is None:
            return bias
        return bias + (self.seam.anchor_cent - bias) * self.seam.weight(slot)

    def forecast(self, known: Mapping[datetime, float], start: datetime, end: datetime) -> dict[datetime, float]:
        """Prices for the UTC slots of ``[start, end)``; ``known`` is not used (the bias comes from the caller)."""
        result: dict[datetime, float] = {}
        slot = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        while slot < end_utc:
            epex = self._predict(slot)
            if epex is not None:
                offset = self.offset_cent(slot)
                result[slot] = float(epex) if offset is None else float(epex) + offset
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
