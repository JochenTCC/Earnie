"""Monitor tile with the ledger from the runtime folder of the test.

The test sets ``ledger_savings`` in the session state: the dict Chart 2 would draw.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from ui.ledger_kpi import render_ledger_kpi

render_ledger_kpi(
    datetime(2026, 11, 4, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    st.session_state.get("ledger_savings"),
)
