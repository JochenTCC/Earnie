"""Gemeinsame Verbrauchs-UI für Hauskonfigurator, Backtesting und Szenarieneditor."""
from ui.consumption_display.panel import render_consumption_display
from ui.consumption_display.types import ConsumptionDisplayMode

__all__ = ["ConsumptionDisplayMode", "render_consumption_display"]
