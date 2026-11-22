"""AppTest entry: SE deviation calendar and SA segment toggle on a fixed meta (coverage tests).

Session keys set by the test:
- ``_cal_meta``, ``_cal_cases``, ``_cal_anchors`` (ISO strings): calendar input
- ``_toggle_meta``: when set, also renders the SA segment toggle for that meta
Results: ``_cal_returned`` (date or None), ``_toggle_returned``.
"""
from datetime import date

import pandas as pd
import streamlit as st

import ui.backtesting  # noqa: F401  first: ui.backtesting imports the result modules
from ui.backtesting_deviation_calendar import (
    build_deviation_calendar_index,
    render_deviation_calendar,
)
from ui.backtesting_deviation_list import _render_sa_segment_toggle

meta = st.session_state["_cal_meta"]
anchors = [pd.Timestamp(a).to_pydatetime() for a in st.session_state.get("_cal_anchors", [])]
index = build_deviation_calendar_index(
    meta, st.session_state.get("_cal_cases", []), run_anchors=anchors
)
st.session_state["_cal_returned"] = render_deviation_calendar(index, meta)

toggle_meta = st.session_state.get("_toggle_meta")
if toggle_meta is not None:
    st.session_state["_toggle_returned"] = _render_sa_segment_toggle(
        toggle_meta,
        log_dir=st.session_state["_toggle_log_dir"],
        window_anchor="2026-06-25T00:00:00",
        scenario_id="live",
        selected_date=date(2026, 6, 25),
    )
