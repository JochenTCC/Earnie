"""SE forecast mode: what the MILP sees instead of the actuals. Spec ``docs/dev/se-forecast-mode.md``."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd

from data import feed_in_prices
from data.backtesting_prices import (
    BacktestingPriceResources,
    market_for_prices,
    matrix_prices_from_context,
)
from simulation.backtesting_horizon import naive_backtesting_slot
from simulation.historical_cache import HistoricalDataCache

PLAN_PRICE = "price"
PLAN_PV = "pv"
PLAN_LOAD = "load"
PLAN_ALL = (PLAN_PRICE, PLAN_PV, PLAN_LOAD)


def parse_plan_forecast(raw: str | None) -> tuple[str, ...] | None:
    """``None``: no forecast mode. ``""``: the mode without forecasts, plan equals actuals."""
    if raw is None:
        return None
    names = [name.strip().lower() for name in str(raw).split(",") if name.strip()]
    unknown = sorted(set(names) - set(PLAN_ALL))
    if unknown:
        raise ValueError(
            f"plan_forecast kennt {', '.join(PLAN_ALL)}, nicht {', '.join(unknown)}."
        )
    return tuple(name for name in PLAN_ALL if name in names)


class PvForecastSource:
    """PV as forecast 24 h earlier, scaled per calendar month to the booked PV's total.

    The archived forecasts sit about 10 % below the archive that gets booked, even without
    lead time, so a raw series would mostly measure that bias (spec § 3.3).
    """

    def __init__(self, scenario_params: dict, cache: HistoricalDataCache) -> None:
        from data.modeled_climate import ModeledClimateContext

        self._params = scenario_params
        self._cache = cache
        self._climate = ModeledClimateContext.from_scenario(scenario_params)
        self._months: dict[tuple[int, int], pd.Series] = {}

    def _raw_month_kw(self, first: date, last: date) -> pd.Series:
        from data.open_meteo_solar_archive import (
            REFERENCE_WM2,
            fetch_hourly_tilted_irradiance_day1_forecast_wm2_series,
        )

        total: pd.Series | None = None
        for system in self._climate.pv_systems:
            wm2 = fetch_hourly_tilted_irradiance_day1_forecast_wm2_series(
                first,
                last,
                lat=self._climate.lat,
                lon=self._climate.lon,
                tilt=system.surface.tilt_deg,
                azimuth=system.surface.azimuth_deg,
                timezone=self._climate.timezone,
            )
            kw = wm2 / REFERENCE_WM2 * float(system.kwp)
            total = kw if total is None else total + kw
        if total is None:
            hours = pd.date_range(first, last + timedelta(days=1), freq="h", inclusive="left")
            return pd.Series(0.0, index=hours)
        return total

    def _month_kw(self, year: int, month: int) -> pd.Series:
        key = (year, month)
        if key not in self._months:
            first = date(year, month, 1)
            last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            raw = self._raw_month_kw(first, last)
            # The hour repeated in autumn shows up twice on the wall clock; the slots know one.
            raw = raw[~raw.index.duplicated(keep="first")]
            archived = raw.dropna()
            actual_kwh = sum(
                self._cache.get_pv_for_slots(
                    [ts.to_pydatetime() for ts in archived.index], scenario_params=self._params
                )
            )
            forecast_kwh = float(archived.sum())
            if forecast_kwh > 0.0:
                factor = actual_kwh / forecast_kwh
            elif actual_kwh > 0.0:
                raise ValueError(
                    f"PV-Prognose {year}-{month:02d}: Prognose 0 kWh bei gebuchten "
                    f"{actual_kwh:.1f} kWh, nicht skalierbar."
                )
            else:
                factor = 1.0
            self._months[key] = raw * factor
        return self._months[key]

    def kw_for_slots(self, slot_datetimes: list[datetime]) -> list[float]:
        values: list[float] = []
        for slot in slot_datetimes:
            hour = pd.Timestamp(slot).floor("h")
            if hour.tz_localize(self._climate.timezone, ambiguous=True, nonexistent="NaT") is pd.NaT:
                # The spring gap has no forecast hour: hold the last hour before the clock jumps.
                hour -= pd.Timedelta(hours=1)
            value = self._month_kw(slot.year, slot.month).get(hour)
            if value is None or pd.isna(value):
                raise ValueError(
                    f"PV-Prognose: Kein archivierter Lauf für {slot:%Y-%m-%d %H:%M} "
                    "(Open-Meteo Previous Runs beginnt am 2024-01-19)."
                )
            values.append(round(float(value), 3))
        return values


def load_deviation_kw(
    slot_datetimes: list[datetime],
    scenario_params: dict,
    cache: HistoricalDataCache,
) -> list[float]:
    """Baseload from the profile minus the booked baseload; overlays and fixed load stay.

    Zero for a house whose baseload is the profile already (flat or monthly): it has no
    deviation to plan on (spec § 3.2).
    """
    from data.modeled_climate import ModeledClimateContext
    from house_config.planning_flex_bridge import (
        PROFILE_SPEC,
        meter_residual_baseload_kw,
        monthly_residual_baseload_kw,
        resolve_consumption_source,
    )
    from house_config.profile_csv_policy import se_uses_meter_residual_baseload
    from simulation.engine_scenario import _flexible_consumers_from_scenario

    if resolve_consumption_source(scenario_params) != PROFILE_SPEC:
        return cache.get_baseload_profile_deviation_kw(slot_datetimes)
    profile = scenario_params["_house_profile"]
    if not se_uses_meter_residual_baseload(profile):
        return [0.0] * len(slot_datetimes)
    climate = ModeledClimateContext.from_scenario(scenario_params)
    booked, _clipped = meter_residual_baseload_kw(
        profile,
        slot_datetimes,
        climate=climate,
        milp_flex_ids={str(c["id"]) for c in _flexible_consumers_from_scenario(scenario_params)},
    )
    planned = monthly_residual_baseload_kw(profile, slot_datetimes, climate=climate)
    return [plan - book for plan, book in zip(planned, booked)]


class ForecastPlanner:
    """Builds a window's plan matrix from its booking matrix, once per scenario run."""

    def __init__(
        self,
        inputs: Iterable[str],
        *,
        scenario_params: dict,
        cache: HistoricalDataCache,
        prices_df: pd.DataFrame,
        feed_in_settings: feed_in_prices.FeedInSettings,
        price_resources: BacktestingPriceResources | None,
    ) -> None:
        self.inputs = frozenset(inputs)
        unknown = sorted(self.inputs - set(PLAN_ALL))
        if unknown:
            raise ValueError(f"Unbekannte Plan-Prognose: {', '.join(unknown)}.")
        if (PLAN_PRICE in self.inputs) != (price_resources is not None):
            raise ValueError(
                "Forecast-Modus: Die Preisprognose braucht eine Preisstrategie (mirror oder "
                "forecast), und eine Preisstrategie braucht die Preisprognose."
            )
        self._params = scenario_params
        self._cache = cache
        self._prices_df = prices_df
        self._feed_in_settings = feed_in_settings
        self._price_resources = price_resources
        self._pv = PvForecastSource(scenario_params, cache) if PLAN_PV in self.inputs else None

    def _apply_prices(self, plan: list[dict], slots: list[datetime], moment: datetime) -> None:
        from simulation.matrix_builder import _pricing_kwargs_from_scenario

        ctx = self._price_resources.at_planning_moment(moment)
        epex, brutto, sources = matrix_prices_from_context(
            self._prices_df,
            slots,
            ctx,
            planning_moment=moment,
            **_pricing_kwargs_from_scenario(self._params),
        )
        for row, market, price, source in zip(plan, epex, brutto, sources):
            row.update(price_buy=market, k_act=price, price_source=source)
        feed_in_prices.enrich_matrix_feed_in_prices(
            plan,
            self._feed_in_settings,
            market_for=market_for_prices(self._prices_df, ctx, planning_moment=moment),
        )

    def plan_matrix(self, booking_matrix: list[dict], planning_moment: datetime) -> list[dict]:
        """A copy of the window's matrix with the selected inputs replaced; targets stay actual."""
        plan = [dict(row) for row in booking_matrix]
        slots = [naive_backtesting_slot(row["slot_datetime"]) for row in plan]
        if PLAN_PRICE in self.inputs:
            self._apply_prices(plan, slots, planning_moment)
        if self._pv is not None:
            for row, kw in zip(plan, self._pv.kw_for_slots(slots)):
                row["expected_p_pv"] = kw
        if PLAN_LOAD in self.inputs:
            deviation = load_deviation_kw(slots, self._params, self._cache)
            for row, delta in zip(plan, deviation):
                row["expected_p_act"] = round(max(0.0, float(row["expected_p_act"]) + delta), 3)
                if "expected_p_total" in row:
                    row["expected_p_total"] = round(
                        max(0.0, float(row["expected_p_total"]) + delta), 3
                    )
        return plan
