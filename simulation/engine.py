# simulation_engine.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
import config
import profile_manager
from optimizer import (
    simulate_horizon,
    _calculate_step_cost_euro_from_row,
    _total_consumption_kwh_from_rows,
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
    ) -> tuple[list[float], dict[str, float], list[float]]:
        """Grundlast, Flex-Summen und Gesamtlast für ein 24h-Fenster (kW pro Stunde)."""
        self.load()
        idx = pd.DatetimeIndex(slot_datetimes)
        df_window = self._consumption_df.reindex(idx, fill_value=0.0)

        historical_totals = {
            consumer["id"]: round(float(df_window[consumer["name"]].sum()), 3)
            for consumer in config.get_flexible_consumers()
        }
        baseload = df_window["BaseLoad"].round(3).tolist()
        total_load = df_window["Total"].round(3).tolist()
        return baseload, historical_totals, total_load

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
    hourly = prices_df["price_cent_kwh"].resample("h").mean()
    idx = pd.DatetimeIndex(slot_datetimes)
    series = hourly.reindex(idx).ffill().bfill().fillna(0.0)
    return [_brutto_price_cent(float(p)) for p in series.tolist()]


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
        _, _, total_load = cache.get_window_consumption(slots)
        if sum(total_load) <= 0:
            continue
        anchors.append(anchor)
    return anchors


def build_historical_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
) -> tuple[list[dict], dict]:
    """Baut eine 24h-Matrix aus historischen Logs für [Anker-24h, Anker)."""
    slot_datetimes = window_slot_datetimes(anchor)
    baseload, historical_totals, total_load = cache.get_window_consumption(slot_datetimes)
    pv_profile = cache.get_pv_for_slots(slot_datetimes)
    brutto_prices = _brutto_prices_for_slots(prices_df, slot_datetimes)

    matrix = []
    for slot_dt, price, pv, base, total in zip(
        slot_datetimes, brutto_prices, pv_profile, baseload, total_load
    ):
        matrix.append(
            {
                "hour": slot_dt.hour,
                "date": slot_dt.date(),
                "slot_datetime": slot_dt,
                "k_act": price,
                "expected_p_act": base,
                "expected_p_total": total,
                "expected_p_pv": pv,
                "consumption_mode": "logged_day",
                "charging_anchor": anchor,
            }
        )

    meta = {
        "window_end": anchor,
        "historical_totals": historical_totals,
        "historical_total_kwh": round(sum(total_load), 3),
        "baseload_kwh": round(sum(baseload), 3),
        "consumer_daily_targets_kwh": dict(historical_totals),
    }
    return matrix, meta


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
    k_push_cent: float,
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
        _, _, total_load = cache.get_window_consumption(slot_datetimes)
        pv_profile = cache.get_pv_for_slots(slot_datetimes)
        brutto_prices = _brutto_prices_for_slots(prices_df, slot_datetimes)

        for slot_dt, load, pv, price in zip(
            slot_datetimes, total_load, pv_profile, brutto_prices
        ):
            timestamps.append(slot_dt)
            costs.append(
                _hour_cost_without_optimization(load, pv, price, k_push_cent)
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
    """Prüft Grundlast + optimierte Flex-Verbraucher gegen historischen 24h-Gesamtverbrauch."""
    historical_kwh = float(meta["historical_total_kwh"])
    optimized_kwh = _total_consumption_kwh_from_rows(chart_rows)
    diff = round(abs(optimized_kwh - historical_kwh), 3)
    ok = _consumption_within_tolerance(historical_kwh, optimized_kwh)
    return PlausibilityResult(
        window_end=meta["window_end"],
        historical_kwh=historical_kwh,
        optimized_kwh=optimized_kwh,
        diff_kwh=diff,
        ok=ok,
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
            print(
                f"    Ende {item.label}: historisch={item.historical_kwh:.2f} kWh, "
                f"optimiert={item.optimized_kwh:.2f} kWh, Delta={item.diff_kwh:.2f} kWh"
            )
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
) -> tuple[pd.DataFrame, PlausibilityReport]:
    """
    Simuliert in 24h-Fenstern mit historischen Verbrauchsdaten und Flex-Optimierung.
    Fensterende = E-Auto-Fertigstellungszeit (ready_by_hour), Start = 24h davor.
    """
    cache = cache or HistoricalDataCache()
    cache.load()

    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    battery_params = _scenario_to_battery_params(scenario_params)
    k_push = float(scenario_params["k_push_cent"])
    total_hours = len(anchors) * 24
    hours_done = 0
    sim_soc = initial_soc

    all_chart_rows: list[dict] = []
    all_timestamps: list[datetime] = []
    plausibility = PlausibilityReport()

    for anchor in anchors:
        matrix, meta = build_historical_window_matrix(anchor, cache, prices_df)
        chart_rows = simulate_horizon(
            matrix,
            sim_soc,
            battery_params=battery_params,
            k_push=k_push,
            verbose=False,
            consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        )
        plausibility.add(validate_window_consumption(chart_rows, meta))

        sim_soc = float(chart_rows[-1]["Simulierter SoC (%)"])
        all_chart_rows.extend(chart_rows)
        all_timestamps.extend(row["slot_datetime"] for row in matrix[: len(chart_rows)])

        hours_done += len(chart_rows)
        if on_progress is not None:
            on_progress(hours_done, total_hours)

    df_res = pd.DataFrame(
        {
            "sim_cost": [
                _calculate_step_cost_euro_from_row(row, k_push) for row in all_chart_rows
            ],
            "sim_soc": [row["Simulierter SoC (%)"] for row in all_chart_rows],
            "batt_action_kw": [row["Geplante Batterie-Aktion (kW)"] for row in all_chart_rows],
            "steuerbefehl": [row["Steuerbefehl"] for row in all_chart_rows],
        },
        index=pd.DatetimeIndex(all_timestamps),
    )
    df_res.index.name = "ts"
    return df_res, plausibility
