"""Kompakte Legende für Cockpit-Charts: Plotly-Legende aus, klappbare HTML-Legende darunter."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

_COLLAPSIBLE_LEGEND_CSS = """
<style>
.chart-mobile-legend-wrap {
    margin-top: 0;
}
.chart-mobile-legend summary {
    cursor: pointer;
    font-weight: 500;
    padding: 0.35rem 0;
}
.chart-mobile-legend-list {
    list-style: none;
    padding: 0;
    margin: 0.35rem 0 0;
}
.chart-mobile-legend-list li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.3rem;
    font-size: 0.9rem;
    line-height: 1.3;
}
.chart-mobile-legend-swatch {
    display: inline-block;
    width: 14px;
    height: 14px;
    border-radius: 2px;
    flex-shrink: 0;
    border: 1px solid rgba(128, 128, 128, 0.35);
}
</style>
"""

_FALLBACK_LEGEND_COLOR = "#999999"


def inject_mobile_legend_css() -> None:
    st.markdown(_COLLAPSIBLE_LEGEND_CSS, unsafe_allow_html=True)


def _first_color_value(color: Any) -> str | None:
    if color is None:
        return None
    if isinstance(color, (list, tuple)):
        if not color:
            return None
        color = color[0]
    text = str(color).strip()
    return text or None


def _trace_legend_color(trace: Any) -> str | None:
    marker = getattr(trace, "marker", None)
    if marker is not None:
        color = _first_color_value(getattr(marker, "color", None))
        if color:
            return color
        line = getattr(marker, "line", None)
        if line is not None:
            line_color = _first_color_value(getattr(line, "color", None))
            if line_color:
                return line_color
    line = getattr(trace, "line", None)
    if line is not None:
        color = _first_color_value(getattr(line, "color", None))
        if color:
            return color
    fillcolor = getattr(trace, "fillcolor", None)
    return _first_color_value(fillcolor)


def _legend_group_key(trace: Any, name: str) -> str:
    group = getattr(trace, "legendgroup", None)
    if group:
        return str(group)
    return name


def legend_entries_from_figure(fig) -> list[tuple[str, str]]:
    """Name und Farbe je Legenden-Eintrag (Plotly-Reihenfolge, dedupliziert per legendgroup)."""
    entries: list[tuple[str, str]] = []
    seen_groups: set[str] = set()
    for trace in fig.data:
        if not getattr(trace, "showlegend", True):
            continue
        name = getattr(trace, "name", None)
        if not name:
            continue
        name_text = str(name)
        group = _legend_group_key(trace, name_text)
        if group in seen_groups:
            continue
        seen_groups.add(group)
        color = _trace_legend_color(trace) or _FALLBACK_LEGEND_COLOR
        entries.append((name_text, color))
    return entries


def _legend_html(entries: list[tuple[str, str]]) -> str:
    items = []
    for name, color in entries:
        safe_name = html.escape(name)
        safe_color = html.escape(color, quote=True)
        items.append(
            "<li>"
            f'<span class="chart-mobile-legend-swatch" '
            f'style="background-color: {safe_color};"></span>'
            f"<span>{safe_name}</span>"
            "</li>"
        )
    body = "\n".join(items)
    return (
        '<div class="chart-mobile-legend-wrap">'
        '<details class="chart-mobile-legend">'
        "<summary>Legende</summary>"
        f'<ul class="chart-mobile-legend-list">{body}</ul>'
        "</details>"
        "</div>"
    )


def render_collapsible_legend_from_figure(fig) -> None:
    entries = legend_entries_from_figure(fig)
    if not entries:
        return
    st.markdown(_legend_html(entries), unsafe_allow_html=True)
