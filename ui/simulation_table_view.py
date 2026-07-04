"""Scrollbare Simulations-Tabelle mit fixierter Kopfzeile und Uhrzeit-Spalte."""
from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st


def _frozen_table_css(container_id: str) -> str:
    root = f"#{container_id}"
    return f"""
{root} {{
    overflow: auto;
    max-height: min(70vh, 640px);
    width: 100%;
    margin-bottom: 1rem;
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 0.25rem;
}}
{root} table {{
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.875rem;
    white-space: nowrap;
}}
{root} th, {root} td {{
    padding: 0.35rem 0.65rem;
    text-align: left;
    border-bottom: 1px solid rgba(49, 51, 63, 0.12);
}}
{root} thead th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background-color: #f0f2f6;
    box-shadow: 0 1px 0 rgba(49, 51, 63, 0.15);
}}
{root} tbody td:first-child,
{root} thead th:first-child {{
    position: sticky;
    left: 0;
    z-index: 1;
}}
{root} thead th:first-child {{
    z-index: 3;
}}
{root} tbody td:first-child {{
    background-color: #ffffff;
    box-shadow: 1px 0 0 rgba(49, 51, 63, 0.12);
}}
.stApp[data-theme="dark"] {root} thead th {{
    background-color: #262730;
    box-shadow: 0 1px 0 rgba(250, 250, 250, 0.12);
}}
.stApp[data-theme="dark"] {root} tbody td:first-child {{
    background-color: #0e1117;
    box-shadow: 1px 0 0 rgba(250, 250, 250, 0.12);
}}
"""


def build_frozen_simulation_table_html(styler: pd.io.formats.style.Styler) -> str:
    """Pandas-Styler als HTML mit scrollbarem Container und Freeze-Panes."""
    container_id = f"sim-table-{uuid.uuid4().hex[:8]}"
    table_html = styler.hide(axis="index").to_html(index=False, border=0)
    return (
        f"<style>{_frozen_table_css(container_id)}</style>"
        f'<div id="{container_id}" class="sim-table-frozen-wrap">{table_html}</div>'
    )


def render_frozen_simulation_table(styler: pd.io.formats.style.Styler) -> None:
    st.markdown(build_frozen_simulation_table_html(styler), unsafe_allow_html=True)
