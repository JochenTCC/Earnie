"""AppTest entry: SE cost table with the baseline selectors on a fixed log."""
import streamlit as st

import ui.backtesting  # noqa: F401  first: ui.backtesting imports ui.backtesting_results
from ui.backtesting_results import render_annual_cost_table

render_annual_cost_table(
    st.session_state.get(
        "_meta",
        {
            "live_scenario_id": "live",
            "references": ["historical", "l0", "l1"],
            "scenario_ids": ["historical_reference", "ref:live", "ref:dyn", "l1:live", "l1:dyn", "live", "dyn"],
            "reference_by_scenario": {"live": "ref:live", "dyn": "ref:dyn"},
            "l1_by_scenario": {"live": "l1:live", "dyn": "l1:dyn"},
            "labels": {"live": "Live", "dyn": "Dynamisch"},
            "summary": {
                "total_eur": {
                    "historical_reference": 2000.0,
                    "ref:live": 1500.0,
                    "ref:dyn": 1400.0,
                    "l1:live": 1200.0,
                    "l1:dyn": 1100.0,
                    "live": 1000.0,
                    "dyn": 900.0,
                }
            },
        },
    )
)
