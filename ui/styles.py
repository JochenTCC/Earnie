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
