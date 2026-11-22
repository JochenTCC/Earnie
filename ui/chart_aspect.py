"""Constant width:height ratio for the Monitor charts (Chart 1, Chart 2, Sankey).

``ui.chart_aspect_ratios`` in config.json sets the ratio per chart (read on every rerun,
so a change shows after the next page reload, no restart). On desktop and tablet the chart
sits in a box whose height the browser derives from its width (CSS ``aspect-ratio``, at
least ``min_height_px``); the figure drops its own height and stretches to the box. Phones
keep the figure's own height: at 3:1 a chart would be about 120 px high there.
"""
from __future__ import annotations

import re

import streamlit as st

from ui.number_format import localized_figure
from ui.s2_viewport import is_phone_request

DEFAULT_MIN_HEIGHT_PX = 320
_BOX_PREFIX = "chart_aspect_"


def aspect_box_key(chart_id: str, instance: str = "") -> str:
    """Container key of one chart box; *instance* keeps several boxes on a page apart."""
    suffix = re.sub(r"[^A-Za-z0-9_-]", "_", instance or "main")
    return f"{_BOX_PREFIX}{chart_id}__{suffix}"


def aspect_css(chart_id: str, ratio: float, *, min_height_px: int) -> str:
    """CSS for every box of *chart_id*: height from the width at *ratio*, never below the floor."""
    if ratio <= 0:
        raise ValueError(f"Seitenverhältnis von {chart_id} muss > 0 sein (ist {ratio}).")
    selector = f'[class*="st-key-{_BOX_PREFIX}{chart_id}__"]'
    return (
        "<style>"
        f"{selector} {{ aspect-ratio: {ratio:g} / 1; min-height: {int(min_height_px)}px; }}"
        f'{selector} [data-testid="stPlotlyChart"] {{ height: 100%; }}'
        "</style>"
    )


def render_plotly_with_aspect(
    fig,
    *,
    chart_id: str,
    instance: str = "",
    min_height_px: int = DEFAULT_MIN_HEIGHT_PX,
    **plotly_kwargs,
) -> None:
    """``st.plotly_chart`` in the aspect box of *chart_id* (phones: the figure as it is).

    The figure gets the viewer's separators here (``localized_figure``).
    """
    if is_phone_request():
        st.plotly_chart(localized_figure(fig), **plotly_kwargs)
        return
    import config

    ratio = config.get_ui_chart_aspect_ratio(chart_id)
    fig.update_layout(height=None)
    st.markdown(aspect_css(chart_id, ratio, min_height_px=min_height_px), unsafe_allow_html=True)
    with st.container(key=aspect_box_key(chart_id, instance)):
        st.plotly_chart(localized_figure(fig), height="stretch", **plotly_kwargs)
