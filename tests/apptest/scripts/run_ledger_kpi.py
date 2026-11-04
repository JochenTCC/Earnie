"""Monitor tile with the ledger from the runtime folder of the test."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ui.ledger_kpi import render_ledger_kpi

render_ledger_kpi(datetime(2026, 11, 4, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")))
