"""Regression: live price fallback must not NameError on MARKET_ZONE_CH."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from data.live_market_prices import fetch_live_day_ahead_prices


def test_energy_charts_fallback_does_not_nameerror_market_zone_ch(tmp_path, monkeypatch):
    """Regression: Energy-Charts failure must reach aWATTar (import MARKET_ZONE_CH)."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    planning_end = datetime(2026, 10, 6, 7, 26, tzinfo=ZoneInfo("Europe/Vienna"))
    with patch(
        "data.live_market_prices.fetch_energy_charts_prices",
        side_effect=RuntimeError("503 simulated"),
    ):
        with patch(
            "data.live_market_prices._runtime_market_zone",
            return_value="AT",
        ):
            with patch(
                "data.live_market_prices._fetch_awattar_live_fallback",
                return_value=[{"ok": True}],
            ) as fallback:
                result = fetch_live_day_ahead_prices(planning_end=planning_end)
    assert result == [{"ok": True}]
    assert fallback.called
