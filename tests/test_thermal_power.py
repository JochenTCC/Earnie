"""Tests für indicator-basierte Heizleistung (SwimSpa Fall B)."""
from __future__ import annotations

import pandas as pd
import pytest

from data.thermal_power import derive_heating_power_kw, resolve_live_heating_power_kw


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range("2025-06-01", periods=len(values), freq="h")
    return pd.Series(values, index=index)


def test_derive_heating_uses_indicator_and_subtracts_filter():
    total = _series([0.2, 2.5, 3.0])
    heating = _series([0.0, 1.0, 1.0])
    filt = _series([0.0, 1.0, 0.0])
    derived, method = derive_heating_power_kw(
        total,
        heating_active=heating,
        filter_active=filt,
        filter_nominal_kw=0.18,
        heating_threshold_kw=2.0,
    )
    assert method == "indicator"
    assert derived.iloc[0] == 0.0
    assert derived.iloc[1] == pytest.approx(2.32)
    assert derived.iloc[2] == pytest.approx(3.0)


def test_derive_heating_threshold_fallback_without_indicator():
    total = _series([0.5, 2.8, 1.0])
    derived, method = derive_heating_power_kw(
        total,
        heating_active=None,
        filter_active=None,
        filter_nominal_kw=0.18,
        heating_threshold_kw=2.0,
    )
    assert method == "threshold"
    assert derived.tolist() == [0.0, 2.8, 0.0]


def test_resolve_live_heating_power_kw():
    assert resolve_live_heating_power_kw(total_kw=2.98, filter_kw=0.18, heating_active=False) == 0.0
    assert resolve_live_heating_power_kw(total_kw=2.98, filter_kw=0.18, heating_active=True) == 2.8
    assert resolve_live_heating_power_kw(total_kw=2.98, filter_kw=0.18, heating_active=None) is None
