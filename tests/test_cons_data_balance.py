"""Σ cons_data in the SE window must match the Jahresverbrauch of the house profile."""
from __future__ import annotations

import pandas as pd
import pytest

from data.cons_data_balance import cons_data_window_balance

_WINDOW = (pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30"))  # 365 days


def _frame(total_kw: float, *, baseload_kw: float = 0.0, pool_kw: float = 0.0, start="2025-10-01", end="2026-09-30"):
    index = pd.date_range(start, pd.Timestamp(end) + pd.Timedelta(hours=23), freq="h")
    return pd.DataFrame(
        {"total_kw": total_kw, "baseload_kw": baseload_kw, "pool_kw": pool_kw}, index=index
    )


def _profile(annual_kwh: float = 8760.0) -> dict:
    return {
        "annual_kwh": annual_kwh,
        "baseload_kwh": 876.0,
        "consumer_kwh": annual_kwh - 876.0,
        "consumers": [
            {"id": "pool", "type": "generic", "annual_kwh": 0.0,
             "nominal_power_kw": 1.0,
             "schedule": {"runs_per_week": 7, "duration_h": 2.0, "start_hour": 8, "start_shift_h": 0.0}}
        ],
    }


def test_matching_series_is_ok():
    # 1.0 kW constant over 8760 h = 8760 kWh = annual
    result = cons_data_window_balance(_frame(1.0), _profile(), window=_WINDOW, mirror=False)
    assert result["status"] == "ok"
    assert result["message"] is None
    assert result["total_kwh"] == pytest.approx(8760.0)


def test_deviation_beyond_tolerance_warns_with_baseload_suggestion():
    result = cons_data_window_balance(
        _frame(1.2, baseload_kw=0.3), _profile(), window=_WINDOW, mirror=False
    )
    assert result["status"] == "deviation"
    assert result["deviation_rel"] == pytest.approx(0.2)
    assert "Grundlast" in result["message"]
    assert "neu generieren" in result["message"]
    # suggestion removes exactly the surplus from the baseload
    assert result["suggested_baseload_kwh"] == pytest.approx(0.3 * 8760 - 0.2 * 8760)


def test_deviation_within_tolerance_is_ok():
    result = cons_data_window_balance(_frame(1.02), _profile(), window=_WINDOW, mirror=False)
    assert result["status"] == "ok"


def test_incomplete_window_is_reported_not_summed_partially():
    frame = _frame(1.0, end="2026-06-30")
    result = cons_data_window_balance(frame, _profile(), window=_WINDOW, mirror=False)
    assert result["status"] == "incomplete"
    assert "nicht vollständig" in result["message"]


def test_empty_cons_data_is_reported():
    result = cons_data_window_balance(pd.DataFrame(), _profile(), window=_WINDOW, mirror=False)
    assert result["status"] == "incomplete"


def test_mirror_maps_months_before_comparing():
    # Two source years; mirror onto the window must still sum to 365 days
    frame = _frame(1.0, start="2024-10-01", end="2026-09-30")
    result = cons_data_window_balance(frame, _profile(), window=_WINDOW, mirror=True)
    assert result["status"] == "ok"
