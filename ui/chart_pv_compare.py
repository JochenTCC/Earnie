"""Chart 1: PV forecasts of the comparison logger as thin step lines (maintainer install only).

Data: :mod:`runtime_store.pv_forecast_compare_view` (enabled by
``EARNIE_PV_FORECAST_COMPARE_DIR``). One dotted line per source, step shape (the value holds
for the whole hour), on the power axis next to the PV forecast and the measured PV.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go

from runtime_store.pv_forecast_compare_view import source_label
from ui.chart_colors import hsl
from ui.chart_slot_axis import ChartSlotAxis

LEGEND_GROUP = "pv_forecast_compare"
LEGEND_GROUP_TITLE = "Test-Prognosen PV"
# Distinct hues, away from the PV yellow; fixed per source so a line keeps its colour.
_HUES = (210.0, 280.0, 140.0, 330.0, 20.0, 180.0, 60.0, 0.0)


def add_pv_compare_traces(
    fig: go.Figure,
    axis: ChartSlotAxis,
    series: Mapping[str, Sequence[float | None]],
) -> None:
    """One dotted step line per source; ``series`` has one value per chart slot."""
    starts = list(axis.starts)
    if not starts:
        return
    end = starts[-1] + axis.slot_duration(len(starts) - 1)
    x = starts + [end]
    for index, source in enumerate(sorted(series)):
        values = list(series[source])
        if len(values) != len(starts):
            raise ValueError(
                f"Test-Prognose {source!r}: {len(values)} Werte für {len(starts)} Slots."
            )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=values + [values[-1]],
                name=source_label(source),
                mode="lines",
                line=dict(
                    color=hsl(_HUES[index % len(_HUES)], 65.0, 45.0),
                    width=1.5,
                    dash="dot",
                    shape="hv",
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
