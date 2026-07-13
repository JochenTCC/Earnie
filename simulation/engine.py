# simulation_engine.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
import config
from data import profile_manager
from data import feed_in_prices
from data.backtesting_prices import BacktestingPriceResources, matrix_prices_from_context
from data.planning_window import normalize_hour_slot
from data.market_prices import epex_prices_for_slots
from optimizer import (
    simulate_horizon,
    _calculate_step_cost_euro_from_row,
    _delivered_flex_kwh_from_rows,
    _total_consumption_kwh_from_rows,
)
from simulation.baseload_validation import (
    baseload_kwh_from_chart_rows,
    derive_historical_baseload_kwh,
    resolve_hourly_baseload_kw,
)
from simulation.backtesting_horizon import (
    compute_sunrise_planning_at_anchor,
    effective_sunrise_soc_min_index,
    geo_params_from_scenario,
    naive_backtesting_slot,
    overlay_step_consumption_on_matrix,
    step_slot_datetimes,
    truncate_matrix_for_step_simulation,
    window_start_before_anchor,
)
from simulation.horizon_mode import (
    BACKTESTING_STEP_HOURS,
    DEFAULT_HORIZON_MODE,
    FIXED_24H,
    SUNRISE_WINDOW,
    parse_horizon_mode,
)
from optimizer.cbc_solver import (
    reset_cbc_gap_rel_override,
    reset_cbc_strict_time_limit_override,
    set_cbc_gap_rel_override,
    set_cbc_strict_time_limit_override,
)
from optimizer.cbc_events import (
    begin_cbc_event_collection,
    clear_cbc_milp_context,
    count_cbc_events,
    list_cbc_events,
    set_cbc_milp_context,
    take_cbc_events,
)
from simulation.backtesting_snapshots import build_window_snapshot

# Plausibilisierung: optimierter 24h-Verbrauch vs. historischer Gesamtverbrauch
# (MILP min_on-Constraints können kleine Abweichungen erzeugen)
CONSUMPTION_TOLERANCE_KWH = 0.5
CONSUMPTION_TOLERANCE_REL = 0.05


@dataclass
class PlausibilityResult:
    window_end: datetime
    historical_kwh: float
    optimized_kwh: float
    diff_kwh: float
    ok: bool
    historical_baseload_kwh: float | None = None
    optimized_baseload_kwh: float | None = None
    historical_flex_kwh: float | None = None
    optimized_flex_kwh: float | None = None
    baseload_diff_kwh: float | None = None
    flex_diff_kwh: float | None = None

    @property
    def label(self) -> str:
        return self.window_end.strftime("%Y-%m-%d %H:%M")


@dataclass
class PlausibilityReport:
    results: list[PlausibilityResult] = field(default_factory=list)

    @property
    def failed(self) -> list[PlausibilityResult]:
        return [r for r in self.results if not r.ok]

    def add(self, result: PlausibilityResult) -> None:
        self.results.append(result)


class HistoricalDataCache:
    """Lädt Loxone-Verbrauchs-, Flex- und PV-Daten einmalig für tagweise Simulation."""

    def __init__(self, cons_data_path: str | None = None) -> None:
        self._cons_data_path = cons_data_path
        self._consumption_df: pd.DataFrame | None = None
        self._pv_series: pd.Series | None = None

    def load(self) -> None:
        if self._consumption_df is not None:
            return

        if self._cons_data_path:
            from data import cons_data_store

            cons_df = cons_data_store.load_cons_data(self._cons_data_path)
            if cons_df.empty:
                raise ValueError(
                    f"Backtesting benötigt cons_data unter {self._cons_data_path!r}."
                )
            df = profile_manager._cons_data_to_profile_dataframe(cons_df)
            self._consumption_df = df
            self._pv_series = cons_df["pv_kw"]
            return

        df = profile_manager.load_cons_data_profile_dataframe()
        if df is None or df.empty:
            raise ValueError(
                "Backtesting benötigt cons_data_hourly.csv (z. B. via scripts/generate_cons_data.py)."
            )

        self._consumption_df = df
        self._pv_series = profile_manager.load_cons_data_pv_series()

    def get_window_consumption(
        self,
        slot_datetimes: list[datetime],
        *,
        flex_consumer_ids: list[str] | None = None,
    ) -> tuple[list[float], dict[str, float], list[float], list[float]]:
        """Grundlast (CSV), Flex-Summen, Gesamtlast und stündliche Flex-Summe (kW pro Stunde)."""
        from data.cons_data_house_profile import (
            consumer_labels_for_ids,
            expected_cons_data_consumer_ids,
        )

        self.load()
        idx = pd.DatetimeIndex(slot_datetimes)
        df_window = self._consumption_df.reindex(idx, fill_value=0.0)

        consumer_ids = flex_consumer_ids or expected_cons_data_consumer_ids()
        labels = consumer_labels_for_ids(consumer_ids)
        historical_totals: dict[str, float] = {}
        hourly_flex = [0.0] * len(slot_datetimes)
        for consumer_id in consumer_ids:
            label = labels.get(consumer_id, consumer_id)
            if label in df_window.columns:
                series = df_window[label].astype(float)
                historical_totals[consumer_id] = round(float(series.sum()), 3)
                hourly_flex = [
                    round(prev + float(value), 3)
                    for prev, value in zip(hourly_flex, series.tolist())
                ]
            else:
                historical_totals[consumer_id] = 0.0
        baseload = df_window["BaseLoad"].round(3).tolist()
        total_load = df_window["Total"].round(3).tolist()
        return baseload, historical_totals, total_load, hourly_flex

    def get_pv_for_slots(
        self,
        slot_datetimes: list[datetime],
        *,
        scenario_params: dict | None = None,
    ) -> list[float]:
        if scenario_params is not None:
            from data.modeled_climate import pv_kw_for_slots

            return pv_kw_for_slots(slot_datetimes, scenario_params)
        self.load()
        idx = pd.DatetimeIndex(slot_datetimes)
        if self._pv_series is None or self._pv_series.empty:
            return [0.0] * len(slot_datetimes)
        return self._pv_series.reindex(idx, fill_value=0.0).round(3).tolist()

    def cons_data_consumer_ids_present(self) -> set[str]:
        """Hausprofil-Verbraucher-IDs mit Spalte in cons_data (auch wenn 0 kWh im Fenster)."""
        from data.cons_data_house_profile import (
            consumer_labels_for_ids,
            expected_cons_data_consumer_ids,
        )

        self.load()
        consumer_ids = expected_cons_data_consumer_ids()
        if not consumer_ids:
            return set()
        labels = consumer_labels_for_ids(consumer_ids)
        present: set[str] = set()
        for consumer_id in consumer_ids:
            label = labels.get(consumer_id, consumer_id)
            if label in self._consumption_df.columns:
                present.add(consumer_id)
        return present


def _flexible_consumers_from_scenario(scenario_params: dict | None) -> list:
    from house_config.planning_flex_bridge import merge_flexible_consumers

    base = config.get_flexible_consumers(optimizer_only=True)
    if not scenario_params:
        return base
    planning = scenario_params.get("_planning_flex_consumers") or []
    return merge_flexible_consumers(base, planning)


def _charging_schedule_consumer() -> dict | None:
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        sched = consumer.get("charging_schedule")
        if sched and sched.get("enabled"):
            return consumer
    return None


def _ready_hour_for_date(target_date: date) -> int:
    """ready_by_hour am Fenster-Ende (Wochentag/Wochenende des Abfahrtstags)."""
    consumer = _charging_schedule_consumer()
    if not consumer:
        return 0
    sched = consumer["charging_schedule"]
    day_key = "weekend" if target_date.weekday() >= 5 else "weekday"
    day_sched = sched.get(day_key, {})
    return int(day_sched.get("ready_by_hour", 0)) % 24


def window_anchor_for_date(target_date: date) -> datetime:
    """
    Endzeitpunkt des 24h-Optimierungsfensters.
    Mit E-Auto-Ladeplan: ready_by_hour am Abfahrtstag (z. B. 07:00).
    Ohne Ladeplan: Mitternacht des Folgetags (= Kalendertag 00–23 Uhr).
    """
    if _charging_schedule_consumer():
        ready_h = _ready_hour_for_date(target_date)
        return datetime.combine(target_date, time(hour=ready_h))
    return datetime.combine(target_date + timedelta(days=1), time(0))


def window_slot_datetimes(anchor: datetime) -> list[datetime]:
    """24 Stunden unmittelbar vor dem Ankerzeitpunkt (Anker exklusiv)."""
    start = anchor - timedelta(hours=24)
    return [start + timedelta(hours=i) for i in range(24)]


def _scenario_to_battery_params(scenario_params: dict) -> dict:
    """Übersetzt JSON-Szenario-Parameter in das Format des Optimizers."""
    return {
        "battery_capacity_kwh": float(scenario_params["battery_capacity_kwh"]),
        "min_soc": float(scenario_params["battery_min_soc"]),
        "max_soc": float(scenario_params["battery_max_soc"]),
        "max_power_kw": float(scenario_params["battery_max_power_kw"]),
        "efficiency": float(scenario_params["battery_efficiency"]),
    }


def _brutto_prices_for_slots(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
    *,
    scenario_params: dict | None = None,
) -> list[float]:
    from data.backtesting_prices import import_brutto_cent_for_slots, pricing_kwargs_from_resolved

    epex = epex_prices_for_slots(prices_df, slot_datetimes)
    return import_brutto_cent_for_slots(
        [float(p) for p in epex],
        slot_datetimes,
        **pricing_kwargs_from_resolved(scenario_params),
    )


def list_simulation_anchors(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache: HistoricalDataCache,
) -> list[datetime]:
    """Fertigstellungs-Anker im Simulationszeitraum (je Kalendertag ein 24h-Fenster)."""
    cache.load()
    anchors: list[datetime] = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        anchor = window_anchor_for_date(day.date())
        slots = window_slot_datetimes(anchor)
        _, _, total_load, _ = cache.get_window_consumption(slots)
        if sum(total_load) <= 0:
            continue
        anchors.append(anchor)
    return anchors


def _pricing_kwargs_from_scenario(scenario_params: dict | None) -> dict:
    if not scenario_params:
        return {}
    from data.backtesting_prices import pricing_kwargs_from_resolved

    return pricing_kwargs_from_resolved(scenario_params)


def build_historical_matrix_for_slots(
    slot_datetimes: list[datetime],
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    *,
    window_end: datetime,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    charging_anchor: datetime | None = None,
    price_resources: BacktestingPriceResources | None = None,
    planning_moment: datetime | None = None,
    scenario_params: dict | None = None,
) -> tuple[list[dict], dict]:
    """Baut eine Optimierungsmatrix für beliebige stündliche Slots aus historischen Logs."""
    from house_config.planning_flex_bridge import (
        PROFILE_SPEC,
        house_profile_baseload_overlay,
        profile_flat_baseload_kw,
        resolve_consumption_source,
        resolve_profile_spec_flex_targets,
    )

    consumption_source = resolve_consumption_source(scenario_params)
    profile = (scenario_params or {}).get("_house_profile")
    flexible_consumers = None
    flex_consumer_ids = None
    if scenario_params:
        flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
        if flexible_consumers:
            flex_consumer_ids = [consumer["id"] for consumer in flexible_consumers]

    baseload_stored, historical_totals, total_load, hourly_flex = (
        cache.get_window_consumption(
            slot_datetimes,
            flex_consumer_ids=flex_consumer_ids,
        )
    )
    _, all_consumer_totals, reference_total_load, _ = cache.get_window_consumption(
        slot_datetimes
    )
    reference_total_kwh = round(sum(reference_total_load), 3)

    if consumption_source == PROFILE_SPEC:
        if not profile:
            raise ValueError(
                "consumption_source=profile_spec erfordert _house_profile im Szenario."
            )
        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.from_scenario(scenario_params)
        flat_kw = profile_flat_baseload_kw(profile)
        overlay = house_profile_baseload_overlay(
            profile,
            slot_datetimes,
            historical_totals=None,
            cons_data_consumer_ids=set(),
            climate=climate,
        )
        baseload_kw = [round(flat_kw + extra, 3) for extra in overlay]
        historical_baseload_kwh = round(sum(baseload_kw), 3)
        matrix_total_kw = list(baseload_kw)
        consumer_daily_targets_kwh = resolve_profile_spec_flex_targets(
            flexible_consumers or [],
            profile,
            slot_datetimes,
            historical_totals=historical_totals,
        )
        spec_flex_kwh = round(sum(consumer_daily_targets_kwh.values()), 3)
        spec_total_kwh = round(historical_baseload_kwh + spec_flex_kwh, 3)
    else:
        baseload_kw, historical_baseload_kwh = resolve_hourly_baseload_kw(
            total_load, hourly_flex
        )
        if profile:
            from data.modeled_climate import ModeledClimateContext

            climate = ModeledClimateContext.from_scenario(scenario_params)
            cons_data_consumer_ids = cache.cons_data_consumer_ids_present()
            overlay = house_profile_baseload_overlay(
                profile,
                slot_datetimes,
                historical_totals=all_consumer_totals,
                cons_data_consumer_ids=cons_data_consumer_ids,
                climate=climate,
            )
            baseload_kw = [
                round(base + extra, 3) for base, extra in zip(baseload_kw, overlay)
            ]
            historical_baseload_kwh = round(sum(baseload_kw), 3)
        matrix_total_kw = total_load
        consumer_daily_targets_kwh = dict(historical_totals)
        spec_flex_kwh = round(sum(consumer_daily_targets_kwh.values()), 3)
        spec_total_kwh = round(sum(total_load), 3)

    stored_baseload_kwh = round(sum(baseload_stored), 3)
    pv_profile = cache.get_pv_for_slots(
        slot_datetimes,
        scenario_params=scenario_params,
    )
    price_ctx = (
        price_resources.at_planning_moment(planning_moment)
        if price_resources is not None and planning_moment is not None
        else None
    )
    epex_prices, brutto_prices, price_sources = matrix_prices_from_context(
        prices_df,
        slot_datetimes,
        price_ctx,
        planning_moment=planning_moment,
        **_pricing_kwargs_from_scenario(scenario_params),
    )
    anchor = charging_anchor if charging_anchor is not None else window_end

    matrix = []
    for slot_dt, price, epex, pv, base, total, price_source in zip(
        slot_datetimes,
        brutto_prices,
        epex_prices,
        pv_profile,
        baseload_kw,
        matrix_total_kw,
        price_sources,
    ):
        row = {
            "hour": slot_dt.hour,
            "date": slot_dt.date(),
            "slot_datetime": slot_dt,
            "k_act": price,
            "price_buy": epex,
            "price_source": price_source,
            "expected_p_act": base,
            "expected_p_total": total,
            "expected_p_pv": pv,
            "consumption_mode": consumption_source,
            "charging_anchor": anchor,
        }
        matrix.append(row)

    settings = feed_in_settings or config.get_feed_in_settings()
    feed_in_prices.enrich_matrix_feed_in_prices(matrix, settings)

    if consumption_source == PROFILE_SPEC:
        reference_totals = dict(historical_totals)
        meta_historical_totals = dict(consumer_daily_targets_kwh)
        meta_historical_total_kwh = spec_total_kwh
    else:
        reference_totals = dict(historical_totals)
        meta_historical_totals = dict(historical_totals)
        meta_historical_total_kwh = round(sum(total_load), 3)

    meta = {
        "window_end": window_end,
        "consumption_source": consumption_source,
        "spec_baseload_kwh": historical_baseload_kwh,
        "spec_flex_targets_kwh": dict(consumer_daily_targets_kwh),
        "spec_total_kwh": spec_total_kwh,
        "reference_totals": reference_totals,
        "reference_total_kwh": reference_total_kwh,
        "historical_totals": meta_historical_totals,
        "historical_total_kwh": meta_historical_total_kwh,
        "baseload_kwh": historical_baseload_kwh,
        "baseload_stored_kwh": stored_baseload_kwh,
        "baseload_adjustment_kwh": round(
            stored_baseload_kwh - historical_baseload_kwh, 3
        ),
        "consumer_daily_targets_kwh": consumer_daily_targets_kwh,
    }
    if flexible_consumers:
        meta["_flexible_consumers"] = flexible_consumers
    return matrix, meta


def build_historical_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    scenario_params: dict | None = None,
) -> tuple[list[dict], dict]:
    """Baut eine 24h-Matrix aus historischen Logs für [Anker-24h, Anker)."""
    slot_datetimes = window_slot_datetimes(anchor)
    return build_historical_matrix_for_slots(
        slot_datetimes,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
        scenario_params=scenario_params,
    )


def build_sunrise_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    price_resources: BacktestingPriceResources | None = None,
) -> tuple[list[dict], dict, int, list[dict]]:
    """
    Sunrise-MILP-Matrix (Jetzt→SA₂) für einen Backtesting-Schritt ab Anker−24h.

    Returns: (24h-Schritt-Matrix, Meta, sunrise_soc_min_index, volle Planungsmatrix)
    """
    planning_window, sunrise_index = compute_sunrise_planning_at_anchor(
        anchor, scenario_params
    )
    _, _, tz_name = geo_params_from_scenario(scenario_params)
    planning_moment = window_start_before_anchor(anchor, tz_name)
    step_slots = step_slot_datetimes(anchor, tz_name)
    full_slots = [naive_backtesting_slot(dt) for dt in planning_window.slot_datetimes]
    matrix_kwargs = {
        "price_resources": price_resources,
        "planning_moment": planning_moment,
        "scenario_params": scenario_params,
    }
    step_matrix, meta = build_historical_matrix_for_slots(
        step_slots,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
        **matrix_kwargs,
    )
    matrix_full, _full_meta = build_historical_matrix_for_slots(
        full_slots,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
        **matrix_kwargs,
    )
    meta["planning_horizon_hours"] = len(full_slots)
    meta["sunrise_anchor"] = planning_window.sunrise_anchor
    meta["step_slot_datetimes"] = step_slots
    matrix = truncate_matrix_for_step_simulation(list(matrix_full), sunrise_index)
    overlay_step_consumption_on_matrix(matrix, step_matrix)
    return matrix, meta, effective_sunrise_soc_min_index(sunrise_index), matrix_full


def _apply_backtesting_step(
    chart_rows: list[dict],
    matrix: list[dict],
    meta: dict,
    *,
    horizon_mode: str,
) -> tuple[list[dict], list[dict]]:
    """Schneidet Chart-Zeilen auf den 24h-Backtesting-Schritt zu."""
    if horizon_mode == FIXED_24H:
        return chart_rows, matrix
    step_slots = {
        normalize_hour_slot(slot)
        for slot in meta.get("step_slot_datetimes", [])
    }
    if not step_slots:
        raise ValueError("Sunset-Backtesting: step_slot_datetimes fehlen in meta.")

    indices = [
        index
        for index, row in enumerate(matrix)
        if normalize_hour_slot(row["slot_datetime"]) in step_slots
    ]
    if len(indices) != BACKTESTING_STEP_HOURS:
        raise ValueError(
            f"Sunset-Schritt: erwartet {BACKTESTING_STEP_HOURS} Slots, "
            f"gefunden {len(indices)}."
        )
    return [chart_rows[i] for i in indices], [matrix[i] for i in indices]


def _simulate_anchor_step(
    anchor: datetime,
    sim_soc: float,
    *,
    horizon_mode: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    battery_params: dict,
    feed_in_settings: feed_in_prices.FeedInSettings,
    hours_done: int,
    collect_cbc: bool,
    price_resources: BacktestingPriceResources | None = None,
    collect_full_horizon: bool = False,
) -> tuple[
    list[dict],
    list[dict],
    dict,
    float,
    list[dict] | None,
    list[dict] | None,
    int | None,
]:
    """Ein Backtesting-Schritt (24h Output) für fixed_24h oder sunrise_window."""
    sunrise_index = None
    sunrise_soc_min_index = None
    matrix_full: list[dict] | None = None
    if horizon_mode == SUNRISE_WINDOW:
        matrix, meta, sunrise_index, matrix_full = build_sunrise_window_matrix(
            anchor,
            cache,
            prices_df,
            scenario_params,
            feed_in_settings,
            price_resources=price_resources,
        )
        sunrise_soc_min_index = effective_sunrise_soc_min_index(sunrise_index)
    else:
        matrix, meta = build_historical_window_matrix(
            anchor,
            cache,
            prices_df,
            feed_in_settings=feed_in_settings,
            scenario_params=scenario_params,
        )

    chart_rows = simulate_horizon(
        matrix,
        sim_soc,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        simulation_hour_offset=hours_done if collect_cbc else None,
        sunrise_soc_min_index=sunrise_soc_min_index,
        flexible_consumers=_flexible_consumers_from_scenario(scenario_params),
    )
    full_rows: list[dict] | None = None
    full_matrix: list[dict] | None = None
    if collect_full_horizon and matrix_full is not None:
        full_rows = simulate_horizon(
            matrix_full,
            sim_soc,
            battery_params=battery_params,
            verbose=False,
            consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
            simulation_hour_offset=None,
            sunrise_soc_min_index=sunrise_soc_min_index,
            flexible_consumers=_flexible_consumers_from_scenario(scenario_params),
        )
        full_matrix = matrix_full
    chart_rows, matrix = _apply_backtesting_step(
        chart_rows, matrix, meta, horizon_mode=horizon_mode
    )
    new_soc = float(chart_rows[-1]["Simulierter SoC (%)"])
    return (
        chart_rows,
        matrix,
        meta,
        new_soc,
        full_rows,
        full_matrix,
        sunrise_soc_min_index,
    )


def _hour_cost_without_optimization(
    load_kw: float,
    pv_kw: float,
    price_cent: float,
    k_push_cent: float,
) -> float:
    """
    Stromkosten einer Stunde ohne Optimierung:
    historischer Verbrauch minus PV, keine Batterie, kein Flex-Scheduling.
    """
    p_grid = float(load_kw) - float(pv_kw)
    if p_grid >= 0:
        return p_grid * price_cent / 100.0
    return p_grid * k_push_cent / 100.0


HISTORICAL_REFERENCE_ID = "historical_reference"
SCENARIO_REFERENCE_PREFIX = "ref:"


def scenario_reference_id(scenario_id: str) -> str:
    """Eindeutige Referenz-Spalte je Szenario (eigene Tarife)."""
    return f"{SCENARIO_REFERENCE_PREFIX}{scenario_id}"


def is_scenario_reference_id(result_id: str) -> bool:
    return str(result_id).startswith(SCENARIO_REFERENCE_PREFIX)


def resolve_reference_hourly_load(
    cache: HistoricalDataCache,
    slot_datetimes: list[datetime],
    *,
    scenario_params: dict | None = None,
) -> list[float]:
    """Referenz-Gesamtlast (kW) je Slot: Hausprofil-Default oder cons_data."""
    from house_config.planning_flex_bridge import (
        PROFILE_SPEC,
        profile_reference_hourly_load,
        resolve_consumption_source,
    )

    source = resolve_consumption_source(scenario_params)
    profile = (scenario_params or {}).get("_house_profile")
    if source == PROFILE_SPEC and profile:
        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.from_scenario(scenario_params)
        return profile_reference_hourly_load(
            profile, slot_datetimes, climate=climate
        )
    _, _, total_load, _ = cache.get_window_consumption(slot_datetimes)
    return total_load


def compute_historical_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices_df: pd.DataFrame,
    feed_in_settings: feed_in_prices.FeedInSettings,
    cache: HistoricalDataCache | None = None,
    *,
    scenario_params: dict | None = None,
) -> pd.DataFrame:
    """
    Referenzkosten: Referenz-Verbrauch + PV, verrechnet mit Szenario-Tarifen,
    ohne Batterie- oder Flex-Optimierung.
    """
    cache = cache or HistoricalDataCache()
    cache.load()

    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    timestamps: list[datetime] = []
    costs: list[float] = []
    ref_settings = feed_in_settings
    if scenario_params is not None:
        ref_settings = config.get_backtesting_feed_in_settings(
            runtime_override=scenario_params
        )

    for anchor in anchors:
        slot_datetimes = window_slot_datetimes(anchor)
        total_load = resolve_reference_hourly_load(
            cache,
            slot_datetimes,
            scenario_params=scenario_params,
        )
        pv_profile = cache.get_pv_for_slots(
            slot_datetimes,
            scenario_params=scenario_params,
        )
        brutto_prices = _brutto_prices_for_slots(
            prices_df,
            slot_datetimes,
            scenario_params=scenario_params,
        )
        epex_prices = epex_prices_for_slots(prices_df, slot_datetimes)

        for slot_dt, load, pv, price, epex in zip(
            slot_datetimes, total_load, pv_profile, brutto_prices, epex_prices
        ):
            timestamps.append(slot_dt)
            k_push = feed_in_prices.resolve_k_push_act(
                epex, ref_settings, slot_datetime=slot_dt
            )
            costs.append(
                _hour_cost_without_optimization(load, pv, price, k_push)
            )

    df_res = pd.DataFrame({"sim_cost": costs}, index=pd.DatetimeIndex(timestamps))
    df_res.index.name = "ts"
    return df_res


def build_per_scenario_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    scenarios: dict[str, dict],
    *,
    live_scenario_id: str,
    scenario_labels: dict[str, str] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, str]]:
    """
    Referenzkosten je Szenario-Tarifprofil.

    Returns: (zusätzliche Referenz-DataFrames, Labels, scenario_id → reference_id)
    """
    from house_config.planning_flex_bridge import tariff_reference_fingerprint

    labels = scenario_labels or {}
    live_params = scenarios.get(live_scenario_id)
    if live_params is None and scenarios:
        live_params = next(iter(scenarios.values()))
    live_fp = tariff_reference_fingerprint(live_params)

    reference_by_scenario: dict[str, str] = {}
    extra_results: dict[str, pd.DataFrame] = {}
    extra_labels: dict[str, str] = {}

    for scenario_id, params in scenarios.items():
        fp = tariff_reference_fingerprint(params)
        if fp == live_fp:
            reference_by_scenario[scenario_id] = HISTORICAL_REFERENCE_ID
            continue
        ref_id = scenario_reference_id(scenario_id)
        ref_settings = config.get_backtesting_feed_in_settings(runtime_override=params)
        extra_results[ref_id] = compute_historical_reference_costs(
            start,
            end,
            prices_df,
            ref_settings,
            cache=cache,
            scenario_params=params,
        )
        display = labels.get(scenario_id, scenario_id)
        extra_labels[ref_id] = f"Referenz ({display})"
        reference_by_scenario[scenario_id] = ref_id

    return extra_results, extra_labels, reference_by_scenario


def _consumption_within_tolerance(historical_kwh: float, optimized_kwh: float) -> bool:
    diff = abs(optimized_kwh - historical_kwh)
    if diff <= CONSUMPTION_TOLERANCE_KWH:
        return True
    if historical_kwh <= 0:
        return diff <= CONSUMPTION_TOLERANCE_KWH
    return (diff / historical_kwh) <= CONSUMPTION_TOLERANCE_REL


def _plausibility_reference_values(
    meta: dict,
    flexible_consumers: list | None,
) -> tuple[float, float, float, dict[str, float]]:
    """Referenz-kWh für Plausibilität (spec vs. geloggt)."""
    from house_config.planning_flex_bridge import PROFILE_SPEC

    source = meta.get("consumption_source", "logged_day")
    if source == PROFILE_SPEC:
        reference_kwh = float(meta["spec_total_kwh"])
        reference_baseload = float(meta["spec_baseload_kwh"])
        flex_targets = dict(meta.get("spec_flex_targets_kwh") or {})
    else:
        reference_kwh = float(meta["historical_total_kwh"])
        flex_targets = dict(
            meta.get("historical_totals") or meta.get("consumer_daily_targets_kwh", {})
        )
        reference_baseload = float(
            meta.get("baseload_kwh")
            if meta.get("baseload_kwh") is not None
            else derive_historical_baseload_kwh(reference_kwh, flex_targets)
        )
    if flexible_consumers:
        flex_ids = {consumer["id"] for consumer in flexible_consumers}
        flex_targets = {
            key: value for key, value in flex_targets.items() if key in flex_ids
        }
    reference_flex = round(sum(float(v) for v in flex_targets.values()), 3)
    return reference_kwh, reference_baseload, reference_flex, flex_targets


def validate_window_consumption(
    chart_rows: list[dict],
    meta: dict,
) -> PlausibilityResult:
    """Prüft Grundlast und Flex getrennt gegen Referenz-24h-Werte (Spec oder Log)."""
    flexible_consumers = meta.get("_flexible_consumers")
    reference_kwh, reference_baseload, reference_flex, _flex_targets = (
        _plausibility_reference_values(meta, flexible_consumers)
    )

    optimized_baseload = baseload_kwh_from_chart_rows(chart_rows)
    delivered_flex = _delivered_flex_kwh_from_rows(
        chart_rows,
        flexible_consumers=flexible_consumers,
    )
    optimized_flex = round(sum(delivered_flex.values()), 3)
    optimized_kwh = round(optimized_baseload + optimized_flex, 3)

    baseload_ok = _consumption_within_tolerance(
        reference_baseload, optimized_baseload
    )
    flex_ok = _consumption_within_tolerance(reference_flex, optimized_flex)
    total_ok = _consumption_within_tolerance(reference_kwh, optimized_kwh)
    ok = baseload_ok and flex_ok and total_ok

    return PlausibilityResult(
        window_end=meta["window_end"],
        historical_kwh=reference_kwh,
        optimized_kwh=optimized_kwh,
        diff_kwh=round(abs(optimized_kwh - reference_kwh), 3),
        ok=ok,
        historical_baseload_kwh=reference_baseload,
        optimized_baseload_kwh=optimized_baseload,
        historical_flex_kwh=reference_flex,
        optimized_flex_kwh=optimized_flex,
        baseload_diff_kwh=round(abs(optimized_baseload - reference_baseload), 3),
        flex_diff_kwh=round(abs(optimized_flex - reference_flex), 3),
    )


def print_plausibility_report(report: PlausibilityReport) -> None:
    total = len(report.results)
    failed = report.failed
    ok_count = total - len(failed)

    print("\n=== PLAUSIBILISIERUNG (24h-Gesamtverbrauch) ===")
    print(
        f"  {ok_count}/{total} Fenster OK "
        f"(Toleranz: {CONSUMPTION_TOLERANCE_KWH} kWh oder "
        f"{CONSUMPTION_TOLERANCE_REL:.0%} relativ)"
    )
    if failed:
        print(f"  WARN: {len(failed)} Fenster ausserhalb der Toleranz:")
        for item in failed[:10]:
            detail = (
                f"    Ende {item.label}: historisch={item.historical_kwh:.2f} kWh, "
                f"optimiert={item.optimized_kwh:.2f} kWh, Delta={item.diff_kwh:.2f} kWh"
            )
            if item.baseload_diff_kwh is not None and item.flex_diff_kwh is not None:
                detail += (
                    f" | Grundlast Δ={item.baseload_diff_kwh:.2f}, "
                    f"Flex Δ={item.flex_diff_kwh:.2f}"
                )
            print(detail)
        if len(failed) > 10:
            print(f"    ... und {len(failed) - 10} weitere")
    print("===============================================")


def _consumption_kw_columns_from_chart_rows(
    chart_rows: list[dict],
    flexible_consumers: list,
) -> dict[str, list[float]]:
    """Extrahiert optimierte Stundenleistungen (Basislast + Flex je ID) aus Chart-Zeilen."""
    from optimizer.simulation import flexible_consumer_power_kw
    from optimizer.targets import consumer_column_name

    flex_keys = [f"{consumer['id']}_kw" for consumer in flexible_consumers]
    columns: dict[str, list[float]] = {
        "consumption_kw": [],
        "baseload_kw": [],
        **{key: [] for key in flex_keys},
    }
    for row in chart_rows:
        baseload = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        columns["baseload_kw"].append(round(baseload, 4))
        for consumer in flexible_consumers:
            col = consumer_column_name(consumer)
            key = f"{consumer['id']}_kw"
            columns[key].append(round(float(row.get(col, 0.0) or 0.0), 4))
        columns["consumption_kw"].append(
            round(baseload + flexible_consumer_power_kw(row), 4)
        )
    return columns


def _critical_snapshot_kind(
    plausibility_ok: bool,
    new_cbc_events: list[dict],
) -> str:
    if not plausibility_ok:
        return "consumption_tolerance"
    if new_cbc_events:
        return str(new_cbc_events[-1].get("event", "cbc_unknown"))
    return "unknown"


def run_simulation(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache | None = None,
    initial_soc: float = 50.0,
    on_progress=None,
    scenario_id: str | None = None,
    horizon_mode: str = DEFAULT_HORIZON_MODE,
    price_resources: BacktestingPriceResources | None = None,
    snapshot_collector: list[dict] | None = None,
) -> tuple[pd.DataFrame, PlausibilityReport, list[dict]]:
    """
    Simuliert historische Verbrauchsdaten mit Flex-Optimierung.

    horizon_mode:
      - fixed_24h: [Anker−24h, Anker), SOC frei am Fensterende (E-Auto-Anker)
      - sunrise_window: MILP Jetzt→SA₂, SOC_min am Sonnenaufgang; Output weiter 24h/Schritt
    """
    horizon_mode = parse_horizon_mode(horizon_mode)
    if horizon_mode == SUNRISE_WINDOW:
        geo_params_from_scenario(scenario_params)

    cache = cache or HistoricalDataCache()
    cache.load()

    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    battery_params = _scenario_to_battery_params(scenario_params)
    flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
    feed_in_settings = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    gap_token = set_cbc_gap_rel_override(config.get_backtesting_cbc_gap_rel())
    limit_token = set_cbc_strict_time_limit_override(
        config.get_backtesting_cbc_strict_time_limit_sec()
    )
    total_hours = len(anchors) * BACKTESTING_STEP_HOURS
    hours_done = 0
    sim_soc = initial_soc

    all_chart_rows: list[dict] = []
    all_timestamps: list[datetime] = []
    plausibility = PlausibilityReport()
    collect_cbc = scenario_id is not None
    if collect_cbc:
        begin_cbc_event_collection()
        set_cbc_milp_context(scenario_id=scenario_id)

    collect_snapshots = snapshot_collector is not None and scenario_id is not None

    try:
        for anchor in anchors:
            if collect_cbc:
                set_cbc_milp_context(
                    window_anchor=pd.Timestamp(anchor).isoformat(),
                )
            window_initial_soc = sim_soc
            events_before = count_cbc_events() if collect_cbc else 0
            (
                chart_rows,
                matrix,
                meta,
                sim_soc,
                chart_rows_full,
                matrix_full,
                sunrise_soc_min_index,
            ) = _simulate_anchor_step(
                anchor,
                sim_soc,
                horizon_mode=horizon_mode,
                cache=cache,
                prices_df=prices_df,
                scenario_params=scenario_params,
                battery_params=battery_params,
                feed_in_settings=feed_in_settings,
                hours_done=hours_done,
                collect_cbc=collect_cbc,
                price_resources=price_resources,
                collect_full_horizon=collect_snapshots,
            )
            if collect_cbc:
                set_cbc_milp_context(
                    consumer_targets_kwh=dict(meta["consumer_daily_targets_kwh"]),
                )
            plausibility_result = validate_window_consumption(chart_rows, meta)
            plausibility.add(plausibility_result)

            if snapshot_collector is not None and scenario_id is not None:
                events_after = count_cbc_events() if collect_cbc else 0
                new_cbc_events = (
                    list_cbc_events()[events_before:events_after]
                    if collect_cbc and events_after > events_before
                    else []
                )
                is_critical = (not plausibility_result.ok) or bool(new_cbc_events)
                if is_critical:
                    snapshot_collector.append(
                        build_window_snapshot(
                            window_anchor=anchor,
                            scenario_id=scenario_id,
                            horizon_mode=horizon_mode,
                            kind=_critical_snapshot_kind(
                                plausibility_result.ok,
                                new_cbc_events,
                            ),
                            initial_soc=window_initial_soc,
                            meta=meta,
                            chart_rows_24h=chart_rows,
                            matrix_24h=matrix,
                            chart_rows_full=chart_rows_full,
                            matrix_full=matrix_full,
                            sunrise_soc_min_index=sunrise_soc_min_index,
                            scenario_params=scenario_params,
                            battery_params=battery_params,
                        )
                    )

            all_chart_rows.extend(chart_rows)
            all_timestamps.extend(row["slot_datetime"] for row in matrix)

            hours_done += len(chart_rows)
            if on_progress is not None:
                on_progress(hours_done, total_hours)
    finally:
        reset_cbc_gap_rel_override(gap_token)
        reset_cbc_strict_time_limit_override(limit_token)
        if collect_cbc:
            clear_cbc_milp_context()

    consumption_columns = _consumption_kw_columns_from_chart_rows(
        all_chart_rows,
        flexible_consumers,
    )
    df_res = pd.DataFrame(
        {
            **consumption_columns,
            "sim_cost": [
                _calculate_step_cost_euro_from_row(row) for row in all_chart_rows
            ],
            "sim_soc": [row["Simulierter SoC (%)"] for row in all_chart_rows],
            "batt_action_kw": [row["Geplante Batterie-Aktion (kW)"] for row in all_chart_rows],
            "steuerbefehl": [row["Steuerbefehl"] for row in all_chart_rows],
        },
        index=pd.DatetimeIndex(all_timestamps),
    )
    df_res.index.name = "ts"
    cbc_events = take_cbc_events() if collect_cbc else []
    return df_res, plausibility, cbc_events
