"""ISO-week (legacy wrapper) and rolling-window navigation side by side."""
import streamlit as st

from ui.consumption_comparison_panel import render_iso_week_navigation
from ui.consumption_display.navigation import render_period_navigation
from ui.consumption_display.period import PeriodKind

_SERIES = st.session_state.get("cov_nav_series", [])

week = render_iso_week_navigation(_SERIES, key_prefix="cov_iso", reset_token="t1")
st.markdown(f"ISO_RESULT={week}")

window = render_period_navigation(
    [ts for ts, _ in _SERIES],
    key_prefix="cov_roll",
    period_kind=PeriodKind.ROLLING_7,
    reset_token="t1",
    default_to_latest=True,
)
st.markdown(f"ROLL_RESULT={None if window is None else window.end.date().isoformat()}")
