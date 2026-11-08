"""Account view of a past window (analysis page), with the ledger from the runtime folder of the test."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ui.chart_account_render import render_period_account_chart

tz = ZoneInfo("Europe/Vienna")
start = datetime(2026, 11, 4, 8, 0, tzinfo=tz)
render_period_account_chart(start, start + timedelta(minutes=45))
