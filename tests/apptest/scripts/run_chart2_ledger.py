"""Chart 2 in the Monitor's split mode, with the ledger from the runtime folder of the test."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ui.chart_cumulative_render import render_cumulative_cost_chart
from ui.chart_ledger_savings import load_ledger_chart_savings

tz = ZoneInfo("Europe/Vienna")
slots = [datetime(2026, 11, 4, 8, 0, tzinfo=tz) + timedelta(minutes=15 * i) for i in range(4)]
df = pd.DataFrame(
    {
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "Preis extrapoliert": [False] * 4,
    }
)
render_cumulative_cost_chart(
    df,
    hourly_matched_baseline_cost_euro=[0.0, 0.0, 0.1, 0.1],
    hourly_optimized_cost_euro=[0.0, 0.0, 0.08, 0.08],
    hourly_matched_baseline_consumption_kwh=[0.0, 0.0, 0.5, 0.5],
    hourly_optimized_consumption_kwh=[0.0, 0.0, 0.45, 0.45],
    history_slot_count=2,
    slot_actual_cost_euro=[0.05, 0.05],
    slot_actual_consumption_kwh=[0.2, 0.2],
    ledger_savings=load_ledger_chart_savings(
        slots, 2, window_start=slots[0], window_end=slots[-1] + timedelta(minutes=15)
    ),
)
