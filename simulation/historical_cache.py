"""Historical cons_data / PV cache for backtesting windows."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from data import profile_manager
from optimizer.slot_duration import DEFAULT_DT_H


def _hour_hold_reindex(series_or_frame, slot_datetimes: list[datetime]):
    """Reindex hourly fuel onto QH slots by holding the parent clock-hour value."""
    from optimizer.slot_duration import floor_to_hour_slot

    idx = pd.DatetimeIndex(slot_datetimes)
    parent_idx = pd.DatetimeIndex(
        [floor_to_hour_slot(pd.Timestamp(ts).to_pydatetime()) for ts in slot_datetimes]
    )
    # Map each QH target to its parent hour row/value.
    hourly = series_or_frame.copy()
    if not isinstance(hourly.index, pd.DatetimeIndex):
        hourly.index = pd.DatetimeIndex(hourly.index)
    hourly.index = hourly.index.map(
        lambda ts: floor_to_hour_slot(pd.Timestamp(ts).to_pydatetime())
    )
    # Collapse duplicate hour keys (keep last).
    hourly = hourly[~hourly.index.duplicated(keep="last")]
    held = hourly.reindex(parent_idx)
    held.index = idx
    return held.fillna(0.0)


class HistoricalDataCache:
    """Lädt Loxone-Verbrauchs-, Flex- und PV-Daten einmalig für tagweise Simulation."""

    def __init__(
        self,
        cons_data_path: str | None = None,
        *,
        season_mirror_window: tuple | None = None,
    ) -> None:
        self._cons_data_path = cons_data_path
        self._season_mirror_window = season_mirror_window
        self._consumption_df: pd.DataFrame | None = None
        self._pv_series: pd.Series | None = None

    def _maybe_season_mirror(self, cons_df: pd.DataFrame) -> pd.DataFrame:
        from data.cons_data_season_mirror import (
            is_season_mirror_enabled,
            season_mirror_cons_dataframe,
            wall_clock_simulation_window,
        )

        if not is_season_mirror_enabled():
            return cons_df
        window = self._season_mirror_window
        if window is None:
            window = wall_clock_simulation_window()
        return season_mirror_cons_dataframe(
            cons_df,
            target_start=window[0],
            target_end=window[1],
        )

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
            cons_df = self._maybe_season_mirror(cons_df)
            df = profile_manager._cons_data_to_profile_dataframe(cons_df)
            self._consumption_df = df
            self._pv_series = cons_df["pv_kw"]
            return

        from data import cons_data_store

        cons_df = cons_data_store.load_cons_data()
        if cons_df.empty:
            raise ValueError(
                "Backtesting benötigt cons_data.csv (z. B. via scripts/generate_cons_data.py)."
            )
        cons_df = self._maybe_season_mirror(cons_df)
        self._consumption_df = profile_manager._cons_data_to_profile_dataframe(cons_df)
        self._pv_series = cons_df["pv_kw"]

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
        df_window = _hour_hold_reindex(self._consumption_df, slot_datetimes)

        consumer_ids = flex_consumer_ids or expected_cons_data_consumer_ids()
        labels = consumer_labels_for_ids(consumer_ids)
        historical_totals: dict[str, float] = {}
        hourly_flex = [0.0] * len(slot_datetimes)
        for consumer_id in consumer_ids:
            label = labels.get(consumer_id, consumer_id)
            if label in df_window.columns:
                series = df_window[label].astype(float)
                historical_totals[consumer_id] = round(
                    float(series.sum()) * float(DEFAULT_DT_H), 3
                )
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
            from simulation.matrix_builder import _imported_pv_kw_for_slots
            imported = _imported_pv_kw_for_slots(slot_datetimes, scenario_params)
            if imported is not None:
                return imported
            from data.modeled_climate import pv_kw_for_slots

            return pv_kw_for_slots(slot_datetimes, scenario_params)
        self.load()
        if self._pv_series is None or self._pv_series.empty:
            return [0.0] * len(slot_datetimes)
        return (
            _hour_hold_reindex(self._pv_series, slot_datetimes).round(3).tolist()
        )

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


