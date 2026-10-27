"""Coverage for data.data_loader simulation-window helpers."""
from __future__ import annotations

import pandas as pd
import pytest

from data import data_loader as dl


def test_last_complete_month_end_on_month_end():
    assert dl.last_complete_month_end(pd.Timestamp("2024-06-30")) == pd.Timestamp(
        "2024-06-30"
    )


def test_last_complete_month_end_mid_month():
    assert dl.last_complete_month_end(pd.Timestamp("2024-06-15")) == pd.Timestamp(
        "2024-05-31"
    )


def test_resolve_simulation_window_invalid_when_start_after_end(monkeypatch):
    monkeypatch.setattr(
        "data.cons_data_season_mirror.is_season_mirror_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "data.profile_manager.get_cons_data_date_bounds",
        lambda: (pd.Timestamp("2024-06-15").date(), pd.Timestamp("2024-06-20").date()),
    )
    with pytest.raises(ValueError, match="keinen vollständigen Kalendermonat"):
        dl.resolve_simulation_window()
