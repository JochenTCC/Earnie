"""Zeitachse und Hilfsfunktionen für Plotly-Charts."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from data.planning_window import UiChartWindow, normalize_hour_slot

def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return number


def _optional_float(value) -> float | None:
    """Wie _safe_float, aber None/NaN bleiben None (kein Default)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _line_plot_float(value) -> float:
    """Plotly-Linienwert: fehlende Messwerte als NaN (Lücken)."""
    parsed = _optional_float(value)
    return float("nan") if parsed is None else parsed


def _safe_int_flag(value) -> int:
    return int(_safe_float(value, 0.0))


@dataclass(frozen=True)
class ChartSlotAxis:
    """
    Zeitbasierte Plotly-X-Achse (type=date).

    Jede Chart-Zeile hat ``slot_datetime`` = Slotbeginn (volle Stunde oder Viertelstunde).
    Plotly erhält echte Zeitstempel — kein Index 0..n-1 mehr.

    **Warum früher Index + Verschiebungen?**
    Historisch lief die X-Achse als ``linear`` mit Tick-Labels aus ``Uhrzeit``, während
    Traces intern mit Slot-Indizes 0..n-1 rechneten. Ein Slot i wurde als Mitte bei x=i
    dargestellt (sichtbarer Bereich [-0.5, n-0.5]). Daraus folgten die Korrekturen:

    | Trace / Element | Index-Offset | Bedeutung (jetzt: Anteil × ``step`` ab Slotbeginn) |
    |-----------------|--------------|-----------------------------------------------------|
    | HV-Linien (Preis, kum. Kosten) | −0.5 | Wert gilt ab Slotbeginn (Treppenfunktion) |
    | Energiebilanz-Balken | +0.05 | Gleiche X-Position (gestapelt, ``barmode=overlay``) |
    | ``add_vrect`` / Jetzt-Linie | Index ± 0.5 | Zonen- und Marker-Grenzen zwischen Sloträndern |

    Konstanten unten (``_LINE_ANCHOR_*``, ``_BAR_CENTER_NUDGE``) sind die zeitliche
    Entsprechung dieser Index-Brüche.
    """

    starts: pd.Series
    step: timedelta

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        *,
        slot_datetimes: tuple[datetime, ...] | None = None,
    ) -> ChartSlotAxis:
        if "slot_datetime" in df.columns:
            starts = pd.to_datetime(df["slot_datetime"])
        elif slot_datetimes is not None:
            if len(slot_datetimes) != len(df):
                raise ValueError(
                    f"slot_datetimes ({len(slot_datetimes)} Einträge) "
                    f"passt nicht zur DataFrame-Länge ({len(df)})."
                )
            starts = pd.Series(list(slot_datetimes))
        else:
            raise ValueError(
                "Chart-Daten benötigen Spalte 'slot_datetime' "
                "oder explizites slot_datetimes-Tuple."
            )
        return cls(starts=starts, step=cls._infer_step(starts))

    @staticmethod
    def _infer_step(starts: pd.Series) -> timedelta:
        if len(starts) < 2:
            return timedelta(hours=1)
        diffs = starts.diff().dropna()
        positive = diffs[diffs > timedelta(0)]
        if positive.empty:
            return timedelta(hours=1)
        return timedelta(seconds=float(positive.dt.total_seconds().median()))

    def slot_duration(self, index: int) -> timedelta:
        """Dauer eines Slots (15 min oder 1 h — aus Nachbar-Slots abgeleitet)."""
        if index + 1 < len(self.starts):
            diff = self.starts.iloc[index + 1] - self.starts.iloc[index]
            if diff > timedelta(0):
                return diff
        if index > 0:
            diff = self.starts.iloc[index] - self.starts.iloc[index - 1]
            if diff > timedelta(0):
                return diff
        return self.step

    def _offset_for(self, index: int, fraction: float) -> pd.Timedelta:
        seconds = self.slot_duration(index).total_seconds() * fraction
        return pd.to_timedelta(seconds, unit="s")

    def at(self, index_slice, fraction: float) -> pd.Series:
        """Zeitpunkt = Slotbeginn + ``fraction`` × Slotdauer (0=Beginn, 0.5=Mitte, 1=Ende)."""
        if isinstance(index_slice, int):
            return pd.Series([self.starts.iloc[index_slice] + self._offset_for(index_slice, fraction)])
        if isinstance(index_slice, slice):
            indices = list(range(*index_slice.indices(len(self.starts))))
        else:
            indices = list(range(len(self.starts)))
        times = [
            self.starts.iloc[i] + self._offset_for(i, fraction)
            for i in indices
        ]
        return pd.Series(times)

    def legacy_index_time(self, index: float) -> datetime:
        """
        Altes Index-X (Slot k zentriert bei x=k, Bereich ±0.5) → Zeitstempel.

        Index −0.5 = ``starts[0]``; Index 0 = Slotmitte; Index k−0.5 = ``starts[k]``.
        Nutzt die echte Slot-Dauer je Zeile (gemischte 15-min/1-h-Auflösung).
        """
        if len(self.starts) == 0:
            raise ValueError("ChartSlotAxis.starts darf nicht leer sein.")
        slot_idx = int(math.floor(index + 0.5))
        if slot_idx < 0:
            return self.starts.iloc[0].to_pydatetime()
        if slot_idx >= len(self.starts):
            last = len(self.starts) - 1
            within = index - (last - 0.5)
            duration = self.slot_duration(last)
            return (self.starts.iloc[last] + duration * within).to_pydatetime()
        within = index - (slot_idx - 0.5)
        duration = self.slot_duration(slot_idx)
        return (self.starts.iloc[slot_idx] + duration * within).to_pydatetime()

    def bar_width_ms(self, width_fraction: float, index: int | None = None) -> float:
        """Plotly ``go.Bar``-Breite auf Datumsachse (Millisekunden)."""
        duration = self.slot_duration(index) if index is not None else self.step
        return duration.total_seconds() * 1000.0 * width_fraction

    def x_range(self, *, range_start: datetime | None = None) -> list[datetime]:
        """Sichtbarer X-Bereich; ``range_start`` = SA₀/SA₁-Fensteranfang (Spec §4)."""
        left = self.legacy_index_time(-0.5)
        if range_start is not None:
            anchor = pd.Timestamp(range_start)
            if anchor > left:
                left = anchor.to_pydatetime()
        return [
            left,
            self.legacy_index_time(len(self.starts) - 0.5),
        ]

    def slice(self, start: int, end: int) -> ChartSlotAxis:
        """Teilfenster für Segment-Traces (behält ``step`` bei)."""
        return ChartSlotAxis(
            starts=self.starts.iloc[start:end].reset_index(drop=True),
            step=self.step,
        )


_LINE_ANCHOR_SLOT_START = 0.0


_LINE_ANCHOR_SLOT_CENTER = 0.5


_BAR_CENTER_NUDGE = 0.05


_BATTERY_BAR_WIDTH_FRACTION = 0.9


_EMPTY_FLOAT_SERIES = pd.Series(dtype=float)


def _empty_chart_time_series() -> pd.Series:
    return pd.Series(dtype=object)


def _chart_time_series(times: list[datetime]) -> pd.Series:
    """Plotly-X in Planungszeitzone — kein ``datetime64[ns, UTC]`` (sonst +2 h Versatz)."""
    if not times:
        return _empty_chart_time_series()
    return pd.Series(times)


def _anchor_fraction_from_legacy_shift(x_shift: float) -> float:
    """Legacy Index-Verschiebung (−0.5 = Slotbeginn, 0 = Mitte) → Anteil ab Slotbeginn."""
    return 0.5 + x_shift


def _slot_time_in_chart(
    slots: tuple[datetime, ...] | list[datetime],
    moment: datetime,
) -> datetime | None:
    if not slots:
        return None
    target = normalize_hour_slot(moment)
    if target in slots:
        return target
    for slot in slots:
        if slot == moment:
            return slot
    return None


def _slot_index_before(axis: ChartSlotAxis, moment: datetime) -> int:
    """Letzter Index mit Slotbeginn strikt vor ``moment``."""
    for index in range(len(axis.starts) - 1, -1, -1):
        if axis.starts.iloc[index] < moment:
            return index
    return -1


def _axis_x_bounds(
    axis: ChartSlotAxis,
    *,
    range_start: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Linker/rechter X-Achsenrand (inkl. ``range_start`` = SA₀/SA₁)."""
    return tuple(axis.x_range(range_start=range_start))  # type: ignore[return-value]


def _zone_slot_left(axis: ChartSlotAxis, index: int) -> datetime:
    return axis.legacy_index_time(index - 0.5)


def _zone_slot_right(axis: ChartSlotAxis, index: int) -> datetime:
    return axis.legacy_index_time(index + 0.5)


def _slot_index_at_or_after(axis: ChartSlotAxis, moment: datetime) -> int | None:
    for index, slot in enumerate(axis.starts):
        if slot >= moment:
            return index
    return None


def _zone_right_edge(axis: ChartSlotAxis, moment: datetime) -> datetime:
    """Rechter Rand des letzten Slots mit Beginn strikt vor ``moment``."""
    history_end_idx = _slot_index_before(axis, moment)
    if history_end_idx < 0:
        return moment
    return _zone_slot_right(axis, history_end_idx)


def _zone_left_edge(axis: ChartSlotAxis, moment: datetime) -> datetime:
    """Linker Rand des ersten Slots mit Beginn >= ``moment``."""
    index = _slot_index_at_or_after(axis, moment)
    if index is None:
        last = len(axis.starts) - 1
        if last < 0:
            raise ValueError("ChartSlotAxis.starts darf nicht leer sein.")
        return _zone_slot_right(axis, last)
    return _zone_slot_left(axis, index)


def _history_zone_x1(
    axis: ChartSlotAxis,
    history_end: datetime,
    *,
    x_right: datetime,
    fill_to_axis_end: bool,
) -> datetime:
    """Rechter Grauzonen-Rand: bis History-Grenze oder voller Achsenrand."""
    if fill_to_axis_end:
        return x_right
    return _zone_right_edge(axis, history_end)


def _forecast_zone_x0(
    axis: ChartSlotAxis,
    forecast_start: datetime,
    x_left: datetime,
) -> datetime:
    """Linker Grünzonen-Rand: ab ``forecast_start``, mindestens ``x_left``."""
    for index, slot in enumerate(axis.starts):
        if slot == forecast_start:
            return max(_zone_slot_left(axis, index), x_left)
    return max(forecast_start, x_left)


def _slot_indices_for_hour(axis: ChartSlotAxis, hour: datetime) -> list[int]:
    indices: list[int] = []
    for index in range(len(axis.starts)):
        slot = axis.starts.iloc[index].to_pydatetime()
        if normalize_hour_slot(slot) == hour:
            indices.append(index)
    return indices


def _chart_xaxis_config(axis: ChartSlotAxis, *, range_start: datetime | None = None) -> dict:
    step_minutes = axis.step.total_seconds() / 60.0
    if step_minutes >= 60:
        dtick = 3600000 * 4
        axis_title = "Uhrzeit (Stunden-Slots)"
    else:
        dtick = 3600000
        axis_title = "Uhrzeit (15-Min-Slots)"
    x0, x1 = axis.x_range(range_start=range_start)
    return dict(
        title=axis_title,
        type="date",
        tickformat="%d.%m. %H:%M",
        dtick=dtick,
        range=[x0, x1],
    )


def _battery_bar_times(axis: ChartSlotAxis, index_slice) -> pd.Series:
    """Batterie-Balken: leicht nach rechts versetzt (früher ``bar_offset`` +0.05)."""
    return axis.at(index_slice, _LINE_ANCHOR_SLOT_CENTER + _BAR_CENTER_NUDGE)


def _hv_line_endpoint_time(axis: ChartSlotAxis) -> datetime:
    """Zeitpunkt am Ende des letzten Slots (HV-Linien, früher Index n−0.5)."""
    return axis.legacy_index_time(len(axis.starts) - 0.5)

