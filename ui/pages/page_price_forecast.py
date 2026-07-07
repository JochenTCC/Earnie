"""Preis-Prognose-Seite (Dev): wrappt ui/price_forecast.py (Controls im Body)."""
from __future__ import annotations

from ui.price_forecast import render_price_forecast_block


def render() -> None:
    render_price_forecast_block()
