# simulation_engine.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
import config
from data import profile_manager
from data import feed_in_prices
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
    compute_sunset_planning_at_anchor,
    geo_params_from_scenario,
    naive_backtesting_slot,
    step_slot_datetimes,
    truncate_matrix_for_step_simulation,
)
from simulation.horizon_mode import (
    BACKTESTING_STEP_HOURS,
    DEFAULT_HORIZON_MODE,
    FIXED_24H,
    SUNSET_WINDOW,
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
    set_cbc_milp_context,
    take_cbc_events,
)

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

    def __init__(self) -> None:
        self._consumption_df: pd.DataFrame | None = None
        self._pv_series: pd.Series | None = None

    def load(self) -> None:
        if self._consumption_df is not None:
            return

        df = profile_manager.load_cons_data_profile_dataframe()
        if df is None or df.empty:
            raise ValueError(
                "Backtesting benötigt cons_data_hourly.csv (z. B. via scripts/generate_cons_data.py)."
            )

        self._consumption_df = df
        self._pv_series = profile_manager.load_cons_data_pv_series()

    def get_window_consumption(
        self, slot_datetimes: list[datetime]
    ) -> tuple[list[float], dict[str, float], list[float], list[float]]:
        """Grundlast (CSV), Flex-Summen, Gesamtlast und stündliche Flex-Summe (kW pro Stunde)."""
        self.load()
        idx = pd.DatetimeIndex(slot_datetimes)
        df_window = self._consumption_df.reindex(idx, fill_value=0.0)

        flex_cols = [consumer["name"] for consumer in config.get_flexible_consumers()]
        historical_totals = {
            consumer["id"]: round(float(df_window[consumer["name"]].sum()), 3)
            for consumer in config.get_flexible_consumers()
        }
        baseload = df_window["BaseLoad"].round(3).tolist()
        total_load = df_window["Total"].round(3).tolist()
        hourly_flex = df_window[flex_cols].sum(axis=1).round(3).tolist()
        return baseload, historical_totals, total_load, hourly_flex

    def get_pv_for_slots(self, slot_datetimes: list[datetime]) -> list[float]:
        self.load()
        idx = pd.DatetimeIndex(slot_datetimes)
        if self._pv_series is None or self._pv_series.empty:
            return [0.0] * len(slot_datetimes)
        return self._pv_series.reindex(idx, fill_value=0.0).round(3).tolist()


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


def _brutto_price_cent(epex_cent: float) -> float:
    fix_aufschlag = config.get("FIX_AUFSCHLAG_CENT", cast=float)
    netzverlust = config.get("NETZVERLUST_FAKTOR", cast=float)
    mwst_faktor = config.get("MWST_AUSTRIA_FAKTOR", cast=float)
    return round((epex_cent * netzverlust + fix_aufschlag) * mwst_faktor, 4)


def _brutto_prices_for_slots(
    prices_df: pd.DataFrame, slot_datetimes: list[datetime]
) -> list[float]:
    return [
        _brutto_price_cent(epex)
        for epex in epex_prices_for_slots(prices_df, slot_datetimes)
    ]


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


def build_historical_matrix_for_slots(
    slot_datetimes: list[datetime],
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    *,
    window_end: datetime,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    charging_anchor: datetime | None = None,
) -> tuple[list[dict], dict]:
    """Baut eine Optimierungsmatrix für beliebige stündliche Slots aus historischen Logs."""
    baseload_stored, historical_totals, total_load, hourly_flex = (
        cache.get_window_consumption(slot_datetimes)
    )
    baseload_kw, historical_baseload_kwh = resolve_hourly_baseload_kw(
        total_load, hourly_flex
    )
    stored_baseload_kwh = round(sum(baseload_stored), 3)
    pv_profile = cache.get_pv_for_slots(slot_datetimes)
    epex_prices = epex_prices_for_slots(prices_df, slot_datetimes)
    brutto_prices = [_brutto_price_cent(epex) for epex in epex_prices]
    anchor = charging_anchor if charging_anchor is not None else window_end

    matrix = []
    for slot_dt, price, epex, pv, base, total in zip(
        slot_datetimes, brutto_prices, epex_prices, pv_profile, baseload_kw, total_load
    ):
        matrix.append(
            {
                "hour": slot_dt.hour,
                "date": slot_dt.date(),
                "slot_datetime": slot_dt,
                "k_act": price,
                "price_buy": epex,
                "expected_p_act": base,
                "expected_p_total": total,
                "expected_p_pv": pv,
                "consumption_mode": "logged_day",
                "charging_anchor": anchor,
            }
        )

    settings = feed_in_settings or config.get_feed_in_settings()
    feed_in_prices.enrich_matrix_feed_in_prices(matrix, settings)

    meta = {
        "window_end": window_end,
        "historical_totals": historical_totals,
        "historical_total_kwh": round(sum(total_load), 3),
        "baseload_kwh": historical_baseload_kwh,
        "baseload_stored_kwh": stored_baseload_kwh,
        "baseload_adjustment_kwh": round(
            stored_baseload_kwh - historical_baseload_kwh, 3
        ),
        "consumer_daily_targets_kwh": dict(historical_totals),
    }
    return matrix, meta


def build_historical_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
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
    )


def build_sunset_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
) -> tuple[list[dict], dict, int]:
    """
    Sunset-MILP-Matrix (Jetzt→SA₂) für einen Backtesting-Schritt ab Anker−24h.

    Returns: (volle Matrix, Meta für den 24h-Schritt, sunrise_soc_min_index)
    """
    planning_window, sunrise_index = compute_sunset_planning_at_anchor(
        anchor, scenario_params
    )
    _, _, tz_name = geo_params_from_scenario(scenario_params)
    step_slots = step_slot_datetimes(anchor, tz_name)
    full_slots = [naive_backtesting_slot(dt) for dt in planning_window.slot_datetimes]
    matrix, _full_meta = build_historical_matrix_for_slots(
        full_slots,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
    )
    _, meta = build_historical_matrix_for_slots(
        step_slots,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
    )
    meta["planning_horizon_hours"] = len(full_slots)
    meta["sunrise_anchor"] = planning_window.sunrise_anchor
    meta["step_slot_datetimes"] = step_slots
    matrix = truncate_matrix_for_step_simulation(matrix, sunrise_index)
    return matrix, meta, sunrise_index


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
) -> tuple[list[dict], list[dict], dict, float]:
    """Ein Backtesting-Schritt (24h Output) für fixed_24h oder sunset_window."""
    sunrise_index = None
    if horizon_mode == SUNSET_WINDOW:
        matrix, meta, sunrise_index = build_sunset_window_matrix(
            anchor, cache, prices_df, scenario_params, feed_in_settings
        )
    else:
        matrix, meta = build_historical_window_matrix(
            anchor, cache, prices_df, feed_in_settings=feed_in_settings
        )

    chart_rows = simulate_horizon(
        matrix,
        sim_soc,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        simulation_hour_offset=hours_done if collect_cbc else None,
        sunrise_soc_min_index=sunrise_index,
    )
    chart_rows, matrix = _apply_backtesting_step(
        chart_rows, matrix, meta, horizon_mode=horizon_mode
    )
    new_soc = float(chart_rows[-1]["Simulierter SoC (%)"])
    return chart_rows, matrix, meta, new_soc


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


def compute_historical_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices_df: pd.DataFrame,
    feed_in_settings: feed_in_prices.FeedInSettings,
    cache: HistoricalDataCache | None = None,
) -> pd.DataFrame:
    """
    Referenzkosten: historischer Verbrauch + PV, verrechnet mit Börsenpreisen,
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

    for anchor in anchors:
        slot_datetimes = window_slot_datetimes(anchor)
        _, _, total_load, _ = cache.get_window_consumption(slot_datetimes)
        pv_profile = cache.get_pv_for_slots(slot_datetimes)
        brutto_prices = _brutto_prices_for_slots(prices_df, slot_datetimes)
        epex_prices = epex_prices_for_slots(prices_df, slot_datetimes)

        for slot_dt, load, pv, price, epex in zip(
            slot_datetimes, total_load, pv_profile, brutto_prices, epex_prices
        ):
            timestamps.append(slot_dt)
            k_push = feed_in_prices.resolve_k_push_act(
                epex, feed_in_settings, slot_datetime=slot_dt
            )
            costs.append(
                _hour_cost_without_optimization(load, pv, price, k_push)
            )

    df_res = pd.DataFrame({"sim_cost": costs}, index=pd.DatetimeIndex(timestamps))
    df_res.index.name = "ts"
    return df_res


def _consumption_within_tolerance(historical_kwh: float, optimized_kwh: float) -> bool:
    diff = abs(optimized_kwh - historical_kwh)
    if diff <= CONSUMPTION_TOLERANCE_KWH:
        return True
    if historical_kwh <= 0:
        return diff <= CONSUMPTION_TOLERANCE_KWH
    return (diff / historical_kwh) <= CONSUMPTION_TOLERANCE_REL


def validate_window_consumption(
    chart_rows: list[dict],
    meta: dict,
) -> PlausibilityResult:
    """Prüft Grundlast und Flex getrennt gegen historische 24h-Werte."""
    historical_kwh = float(meta["historical_total_kwh"])
    historical_totals = meta.get("historical_totals") or meta.get(
        "consumer_daily_targets_kwh", {}
    )
    historical_baseload = float(
        meta.get("baseload_kwh")
        if meta.get("baseload_kwh") is not None
        else derive_historical_baseload_kwh(historical_kwh, historical_totals)
    )
    historical_flex = round(sum(float(v) for v in historical_totals.values()), 3)

    optimized_baseload = baseload_kwh_from_chart_rows(chart_rows)
    delivered_flex = _delivered_flex_kwh_from_rows(chart_rows)
    optimized_flex = round(sum(delivered_flex.values()), 3)
    optimized_kwh = round(optimized_baseload + optimized_flex, 3)

    baseload_ok = _consumption_within_tolerance(
        historical_baseload, optimized_baseload
    )
    flex_ok = _consumption_within_tolerance(historical_flex, optimized_flex)
    total_ok = _consumption_within_tolerance(historical_kwh, optimized_kwh)
    ok = baseload_ok and flex_ok and total_ok

    return PlausibilityResult(
        window_end=meta["window_end"],
        historical_kwh=historical_kwh,
        optimized_kwh=optimized_kwh,
        diff_kwh=round(abs(optimized_kwh - historical_kwh), 3),
        ok=ok,
        historical_baseload_kwh=historical_baseload,
        optimized_baseload_kwh=optimized_baseload,
        historical_flex_kwh=historical_flex,
        optimized_flex_kwh=optimized_flex,
        baseload_diff_kwh=round(abs(optimized_baseload - historical_baseload), 3),
        flex_diff_kwh=round(abs(optimized_flex - historical_flex), 3),
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
) -> tuple[pd.DataFrame, PlausibilityReport, list[dict]]:
    """
    Simuliert historische Verbrauchsdaten mit Flex-Optimierung.

    horizon_mode:
      - fixed_24h: [Anker−24h, Anker), SOC frei am Fensterende (E-Auto-Anker)
      - sunset_window: MILP Jetzt→SA₂, SOC_min am Sonnenaufgang; Output weiter 24h/Schritt
    """
    horizon_mode = parse_horizon_mode(horizon_mode)
    if horizon_mode == SUNSET_WINDOW:
        geo_params_from_scenario(scenario_params)

    cache = cache or HistoricalDataCache()
    cache.load()

    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    battery_params = _scenario_to_battery_params(scenario_params)
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

    try:
        for anchor in anchors:
            if collect_cbc:
                set_cbc_milp_context(
                    window_anchor=pd.Timestamp(anchor).isoformat(),
                )
            chart_rows, matrix, meta, sim_soc = _simulate_anchor_step(
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
            )
            if collect_cbc:
                set_cbc_milp_context(
                    consumer_targets_kwh=dict(meta["consumer_daily_targets_kwh"]),
                )
            plausibility.add(validate_window_consumption(chart_rows, meta))

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

    df_res = pd.DataFrame(
        {
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
