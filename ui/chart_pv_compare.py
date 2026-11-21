"""Chart 1: PV forecasts of the comparison logger as thin dotted lines (maintainer install only).

Data: :mod:`runtime_store.pv_forecast_compare_view` (enabled by
``EARNIE_PV_FORECAST_COMPARE_DIR``). One dotted line per source on the power axis next to the
PV forecast and the measured PV. The logger has one mean kW per clock hour; the line runs
straight from hour centre to hour centre (like the PV line, anchored in the middle of the
time the value stands for), not as a step.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

import plotly.graph_objects as go

from runtime_store.pv_forecast_compare_view import hour_key, source_label
from ui.chart_colors import hsl
from ui.chart_slot_axis import ChartSlotAxis

LEGEND_GROUP = "pv_forecast_compare"
LEGEND_GROUP_TITLE = "Test-Prognosen PV"
# Distinct hues, away from the PV yellow; fixed per source so a line keeps its colour.
_HUES = (210.0, 280.0, 140.0, 330.0, 20.0, 180.0, 60.0, 0.0)


def _hour_groups(axis: ChartSlotAxis) -> list[tuple[int, datetime]]:
    """Per clock hour on the axis: index of its first slot and the centre of its slots.

    The centre lies between the start of the hour's first slot and the end of its last slot,
    so a partly shown hour at the chart edge is anchored in the middle of the shown part.
    """
    starts = list(axis.starts)
    groups: list[tuple[int, datetime]] = []
    first = 0
    for index in range(1, len(starts) + 1):
        if index < len(starts) and hour_key(starts[index]) == hour_key(starts[first]):
            continue
        last = index - 1
        end = starts[last] + axis.slot_duration(last)
        groups.append((first, starts[first] + (end - starts[first]) / 2))
        first = index
    return groups


def _hourly_values(
    source: str, values: Sequence[float | None], groups: Sequence[tuple[int, datetime]], slot_count: int
) -> list[float | None]:
    """One value per hour; all slots of an hour carry the same logger value."""
    bounds = [first for first, _ in groups] + [slot_count]
    hourly: list[float | None] = []
    for position, first in enumerate(bounds[:-1]):
        hour_values = set(values[first : bounds[position + 1]])
        if len(hour_values) != 1:
            raise ValueError(
                f"Test-Prognose {source!r}: Slots ab Index {first} haben in derselben Stunde "
                f"verschiedene Werte {sorted(hour_values, key=str)}."
            )
        hourly.append(hour_values.pop())
    return hourly


def add_pv_compare_traces(
    fig: go.Figure,
    axis: ChartSlotAxis,
    series: Mapping[str, Sequence[float | None]],
) -> None:
    """One dotted line per source, point to point at the hour centres.

    ``series`` has one value per chart slot (the hour's mean kW in every slot of that hour).
    A missing hour (None) leaves a gap.
    """
    starts = list(axis.starts)
    if not starts:
        return
    groups = _hour_groups(axis)
    x = [centre for _, centre in groups]
    for index, source in enumerate(sorted(series)):
        values = list(series[source])
        if len(values) != len(starts):
            raise ValueError(
                f"Test-Prognose {source!r}: {len(values)} Werte für {len(starts)} Slots."
            )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=_hourly_values(source, values, groups, len(starts)),
                name=source_label(source),
                mode="lines",
                line=dict(
                    color=hsl(_HUES[index % len(_HUES)], 65.0, 45.0),
                    width=1.5,
                    dash="dot",
                ),
                connectgaps=False,
                legendgroup=LEGEND_GROUP,
                legendgrouptitle_text=LEGEND_GROUP_TITLE,
                yaxis="y",
                hovertemplate="%{fullData.name}: %{y:.2f} kW<extra></extra>",
            )
        )


TOGGLE_LABEL = "Test-Prognosen PV einblenden"


def pv_compare_series_for_chart(df, *, toggle_key: str) -> dict[str, list[float | None]] | None:
    """Toggle plus series for Chart 1; None when the feature is off or hidden.

    Only with ``EARNIE_PV_FORECAST_COMPARE_DIR`` set. A missing or broken logger file is shown
    as a warning above the chart (the chart itself still renders).
    """
    import streamlit as st

    from runtime_store.pv_forecast_compare_view import (
        FORECASTS_FILENAME,
        PvForecastCompareError,
        cached_series_by_source,
        compare_dir_from_env,
        slot_series,
    )

    directory = compare_dir_from_env()
    if directory is None or df is None or df.empty:
        return None
    if not st.toggle(
        TOGGLE_LABEL,
        value=True,
        key=toggle_key,
        help=(
            "Prognosen aus dem PV-Prognose-Vergleich (Logger), je Stunde der letzte Lauf "
            "vor Beginn der Stunde, summiert über alle PV-Felder. Nur zum Vergleich, "
            "Earnie plant weiter mit seiner eigenen PV-Prognose."
        ),
    ):
        return None
    starts = list(ChartSlotAxis.from_dataframe(df).starts)
    try:
        by_source = cached_series_by_source(directory / FORECASTS_FILENAME, starts)
    except (PvForecastCompareError, KeyError, ValueError) as exc:
        st.warning(f"Test-Prognosen PV nicht lesbar: {exc}")
        return None
    return slot_series(by_source, starts)
