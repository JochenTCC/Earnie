"""Globale Streamlit-Styles."""
from __future__ import annotations

import streamlit as st


def inject_compact_numeric_css() -> None:
    """Kleinere Schrift für Metrik-Zahlen und Tabellen."""
    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] {
            font-size: 0.95rem;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.7rem;
        }
        div[data-testid="stDataFrame"] div[data-testid="stTable"] {
            font-size: 0.8rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_help_hint_css() -> None:
    """Kompakte Hilfe-Popover (Material-Icon, tertiary)."""
    st.markdown(
        """
        <style>
        div[class*="st-key-help_hint__"] button,
        div.st-key-s2_nav_date_popover button {
            min-height: 1.25rem;
            height: 1.25rem;
            padding: 0 0.1rem;
            font-size: 0.9rem;
            line-height: 1;
        }
        div[class*="st-key-help_hint__"] [data-testid="stIconMaterial"],
        div.st-key-s2_nav_date_popover [data-testid="stIconMaterial"] {
            font-size: 0.95rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
