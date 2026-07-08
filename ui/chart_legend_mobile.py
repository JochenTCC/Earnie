"""Mobile Legende: Plotly-Legende auf schmalen Viewports ausblenden, Expander als Ersatz."""
from __future__ import annotations

import streamlit as st

_MOBILE_LEGEND_CSS = """
<style>
@media (max-width: 768px) {
    div[data-testid="stPlotlyChart"] .legend {
        display: none !important;
    }
}
</style>
"""


def inject_mobile_legend_css() -> None:
    st.markdown(_MOBILE_LEGEND_CSS, unsafe_allow_html=True)


def _legend_names_from_figure(fig) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for trace in fig.data:
        name = getattr(trace, "name", None)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(str(name))
    return names


def render_collapsible_legend_from_figure(fig) -> None:
    names = _legend_names_from_figure(fig)
    if not names:
        return
    with st.expander("Legende", expanded=False):
        for name in names:
            st.markdown(f"- {name}")
