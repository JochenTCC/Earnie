"""Edibert P5: OLS forecast through ``OlsForecaster`` (an Edibert forecaster) equals the pre-P5 output.

The golden ``tests/fixtures/edibert_forecast/expected.json`` was recorded with the pre-P5
``resolve_market_slots`` on recorded EU features and Day-Ahead prices (``scripts.ols_forecast_golden``).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from edibert import api

from data.market_prices import MAX_FORECAST_HOURS, resolve_market_slots
from data.ols_forecaster import OlsForecaster
from scripts import ols_forecast_golden as golden

VIENNA = ZoneInfo("Europe/Vienna")


@pytest.fixture(scope="module")
def inputs():
    return golden.load_inputs()


@pytest.fixture(scope="module")
def expected():
    with (golden.FIXTURE_DIR / golden.EXPECTED_FILE).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_golden_covers_every_case(expected):
    assert sorted(case.name for case in golden.iter_cases()) == sorted(expected)


@pytest.mark.parametrize("case", list(golden.iter_cases()), ids=lambda case: case.name)
def test_forecast_matches_pre_p5_output(case, inputs, expected):
    actual = golden.run_case(case, inputs)
    want = expected[case.name]
    assert len(actual) == len(want)
    for got, row in zip(actual, want):
        assert got[0] == row[0] and got[1] == row[1] and got[3] == row[3]
        assert got[2] == pytest.approx(row[2], abs=1e-9)
        assert got[4].keys() == row[4].keys()
        for key, value in row[4].items():
            if isinstance(value, float):
                assert got[4][key] == pytest.approx(value, abs=1e-12)
            else:
                assert got[4][key] == value


def _forecaster(inputs, **kwargs) -> OlsForecaster:
    return OlsForecaster(inputs["model"], inputs["features"]["autumn"], tz=VIENNA, **kwargs)


def _run(forecaster: api.Forecaster, start: datetime, end: datetime):
    """Called through Edibert's interface type, as Edibert would."""
    return forecaster.forecast({}, start, end)


def test_ols_forecaster_quarter_hours_share_their_hour_row(inputs):
    start = datetime(2025, 10, 24, 10, tzinfo=VIENNA).astimezone(UTC)
    prices = _run(_forecaster(inputs), start, start + timedelta(hours=1))
    assert list(prices) == [start + timedelta(minutes=15 * i) for i in range(4)]
    assert len(set(prices.values())) == 1


def test_ols_forecaster_adds_bias(inputs):
    start = datetime(2025, 10, 24, 10, tzinfo=VIENNA).astimezone(UTC)
    end = start + timedelta(hours=2)
    plain = _run(_forecaster(inputs), start, end)
    biased = _run(_forecaster(inputs, bias_cent=1.5), start, end)
    assert {slot: price + 1.5 for slot, price in plain.items()} == pytest.approx(biased)


def test_ols_forecaster_leaves_out_slots_without_features(inputs):
    frame = inputs["features"]["autumn"]
    gap = pd.Timestamp("2025-10-24 11:00")
    forecaster = OlsForecaster(inputs["model"], frame.drop(index=gap), tz=VIENNA)
    start = datetime(2025, 10, 24, 10, tzinfo=VIENNA).astimezone(UTC)
    prices = _run(forecaster, start, start + timedelta(hours=3))
    assert len(prices) == 8
    assert datetime(2025, 10, 24, 11, tzinfo=VIENNA).astimezone(UTC) not in prices


def _forecast_window(inputs, hours_without_prices: float):
    moment = datetime(2025, 10, 24, 0, tzinfo=VIENNA)
    prices = inputs["prices"]["autumn"]
    market = [
        {"timestamp": slot.to_pydatetime().astimezone(VIENNA), "price_buy": float(cent)}
        for slot, cent in prices.items()
        if slot < moment.astimezone(UTC)
    ]
    slots = int(hours_without_prices * 4)
    targets = [(moment.astimezone(UTC) + timedelta(minutes=15 * i)).astimezone(VIENNA) for i in range(slots)]
    return resolve_market_slots(
        market,
        targets,
        missing_price_strategy="forecast",
        forecast_model=inputs["model"],
        forecast_feature_frame=inputs["features"]["autumn"],
        live_bias_enabled=False,
    )


def test_forecast_span_of_72_hours_passes(inputs):
    rows = _forecast_window(inputs, MAX_FORECAST_HOURS)
    assert {row["price_source"] for row in rows} == {"predicted"}


def test_forecast_span_above_72_hours_fails(inputs):
    with pytest.raises(ValueError, match="länger als 72 h"):
        _forecast_window(inputs, MAX_FORECAST_HOURS + 0.25)
