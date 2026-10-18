"""PV input of the L2 backtesting fixture path must be a day curve (0 at night)."""
from __future__ import annotations

import math
import os
from datetime import date, datetime

import pandas as pd
import pytest

from tests.regression.climate_fixture import (
    CLIMATE_FIXTURE_DIR,
    CLIMATE_FIXTURE_NOW,
    ClimateFixtureMissingError,
    frozen_climate_fixture,
)
from tests.regression.loader import DEFAULT_CASES_DIR, load_case
from tests.regression.pv_shape import ImplausiblePvInputError, assert_pv_day_shape

os.environ.setdefault("EARNIE_OFFLINE", "1")

SUMMER_CASE = "REG-O-summer-june"


def _frame(pv_by_hour) -> pd.DataFrame:
    index = pd.date_range("2026-06-25 00:00", periods=96, freq="15min")
    return pd.DataFrame({"pv_kw": [pv_by_hour(ts.hour) for ts in index]}, index=index)


def _bell_kw(hour: int) -> float:
    return max(0.0, 5.2 * math.sin(math.pi * (hour - 5) / 16)) if 5 <= hour <= 21 else 0.0


def test_guard_accepts_day_curve():
    assert_pv_day_shape(_frame(_bell_kw), case_id="t")


def test_guard_rejects_constant_pv_day_and_night():
    with pytest.raises(ImplausiblePvInputError, match="night"):
        assert_pv_day_shape(_frame(lambda _hour: 3.0), case_id="t")


def test_guard_rejects_missing_pv_column():
    with pytest.raises(ImplausiblePvInputError, match="pv_kw"):
        assert_pv_day_shape(pd.DataFrame({"x": [1.0]}), case_id="t")


def test_l2_fixture_path_pv_is_day_curve_from_committed_climate(monkeypatch):
    """Runs offline: climate comes from tests/fixtures/backtesting/open_meteo only."""
    import tests.regression.l2_runner as l2_runner

    monkeypatch.delenv("EARNIE_REGRESSION_RECORD_CLIMATE", raising=False)
    captured: dict[str, pd.DataFrame] = {}

    def _capture(result_df: pd.DataFrame, *, case_id: str) -> None:
        captured["df"] = result_df
        assert_pv_day_shape(result_df, case_id=case_id)

    monkeypatch.setattr(l2_runner, "assert_pv_day_shape", _capture)
    l2_runner.run_l2(load_case(DEFAULT_CASES_DIR / SUMMER_CASE))

    pv = captured["df"]["pv_kw"]
    hours = pd.DatetimeIndex(pv.index).hour
    night = pv[(hours < 3) | (hours >= 23)]
    noon = pv[(hours >= 11) & (hours <= 14)]
    assert not night.empty and not noon.empty
    assert night.abs().max() == 0.0
    assert noon.max() > 1.0
    assert pv.nunique() > 2


def test_climate_fixture_refuses_network_for_missing_key(monkeypatch):
    from data import open_meteo_solar_archive as archive
    from data.open_meteo_solar_archive import TiltedSurface

    monkeypatch.delenv("EARNIE_REGRESSION_RECORD_CLIMATE", raising=False)
    previous_dir = archive.OPEN_METEO_CACHE_DIR
    with frozen_climate_fixture():
        assert archive.OPEN_METEO_CACHE_DIR == CLIMATE_FIXTURE_DIR
        assert datetime.now(CLIMATE_FIXTURE_NOW.tzinfo).date() == CLIMATE_FIXTURE_NOW.date()
        with pytest.raises(ClimateFixtureMissingError, match="Re-record"):
            archive.build_open_meteo_climate_bundle(
                date(2025, 3, 1),
                date(2025, 3, 31),
                lat=1.0,
                lon=2.0,
                timezone="Europe/Vienna",
                surfaces=[TiltedSurface(30.0, 0.0)],
            )
    assert archive.OPEN_METEO_CACHE_DIR == previous_dir
    assert list(CLIMATE_FIXTURE_DIR.glob("1.0000_2.0000_*")) == []
