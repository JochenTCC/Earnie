"""Seam between the last known Day-Ahead price and the first predicted slot.

Bug (2026-11-28, production install): the forecast jumped by ~7 ct/kWh at midnight. The live
bias was the mean residual of the 48 h before the planning start and was added as a constant, so
the first predicted slot sat at the 48 h level instead of near the last known prices. Now the bias
window ends at the first predicted slot, and the first slot starts at the residual of the last
known hours, which decays into the bias.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.market_prices import PRICE_SOURCE_PREDICTED, resolve_market_slots
from data.ols_forecaster import OlsForecaster, SeamAnchor
from data.price_forecast_model import PriceForecastModel

VIENNA = ZoneInfo("Europe/Vienna")
SEAM = datetime(2025, 7, 2, 0, 0, tzinfo=VIENNA)  # first slot without a Day-Ahead price
PLANNING_START = datetime(2025, 7, 1, 22, 0, tzinfo=VIENNA)


def _zero_model() -> PriceForecastModel:
    """OLS that predicts 0 ct everywhere: every residual equals the actual price."""
    return PriceForecastModel(
        version=2,
        feature_names=("intercept",),
        coefficients=(0.0,),
        trained_range_start="2025-01-01",
        trained_range_end="2025-12-31",
        training_rows=1,
        bias_correction_cent_kwh=0.0,
    )


def _feature_frame(start: datetime, end: datetime) -> pd.DataFrame:
    index = pd.date_range(start.replace(tzinfo=None), end.replace(tzinfo=None), freq="h", inclusive="left")
    return pd.DataFrame({"intercept": [1.0] * len(index)}, index=index)


def _market(evening_price: float = 5.0, day_price: float = 20.0) -> list[dict]:
    """48 known hours before the seam: 46 at ``day_price``, the last two at ``evening_price``."""
    rows = []
    for back in range(1, 49):
        slot = SEAM - timedelta(hours=back)
        rows.append({"timestamp": slot, "price_buy": evening_price if back <= 2 else day_price})
    return rows


def _resolve(**kwargs) -> dict[datetime, dict]:
    target = [PLANNING_START + timedelta(minutes=15 * i) for i in range(4 * 14)]
    frame = _feature_frame(SEAM - timedelta(hours=60), SEAM + timedelta(hours=24))
    params = dict(
        missing_price_strategy="forecast",
        forecast_model=_zero_model(),
        forecast_feature_frame=frame,
        live_bias_enabled=True,
        live_bias_cap_cent_kwh=50.0,
        live_bias_feature_frame=frame,
    )
    params.update(kwargs)
    rows = resolve_market_slots(_market(), target, **params)
    return {row["slot_datetime"].astimezone(UTC): row for row in rows}


def _at(rows: dict[datetime, dict], hours_after_seam: float) -> dict:
    return rows[(SEAM + timedelta(hours=hours_after_seam)).astimezone(UTC)]


def test_first_predicted_slot_continues_from_the_last_known_hours():
    rows = _resolve()
    last_known = _at(rows, -0.25)
    first = _at(rows, 0)
    assert first["price_source"] == PRICE_SOURCE_PREDICTED
    # Before the fix: 00:00 sat at the 48 h level (20 ct) right after 5 ct at 23:45.
    assert first["price_buy"] == pytest.approx(last_known["price_buy"])
    assert first["live_bias_cent_kwh"] == pytest.approx(5.0)


def test_seam_offset_decays_linearly_into_the_bias():
    rows = _resolve()
    bias = (46 * 20.0 + 2 * 5.0) / 48  # window ends at the seam, not at the planning start
    assert _at(rows, 4)["price_buy"] == pytest.approx(5.0 + (bias - 5.0) * 0.5)
    assert _at(rows, 8)["price_buy"] == pytest.approx(bias)
    assert _at(rows, 11.75)["price_buy"] == pytest.approx(bias)


def test_seam_offset_steps_per_clock_hour():
    """2026-11-28 on the production install: a per-quarter-hour decay drew sloping lines in the
    chart; the offset steps per clock hour, so the quarter-hours of an hour share one price."""
    rows = _resolve()
    bias = (46 * 20.0 + 2 * 5.0) / 48
    for hour in range(9):
        expected = 5.0 + (bias - 5.0) * min(hour / 8, 1.0)
        prices = [_at(rows, hour + q / 4)["price_buy"] for q in range(4)]
        assert len(set(prices)) == 1, f"hour {hour}: {prices}"
        assert prices[0] == pytest.approx(expected, abs=1e-4), f"hour {hour}"


def test_seam_anchor_steps_on_clock_hours_when_it_starts_mid_hour():
    start = (SEAM + timedelta(minutes=30)).astimezone(UTC)
    seam = SeamAnchor(start=start, anchor_cent=2.0, decay_hours=4.0)
    assert seam.weight(start + timedelta(minutes=15)) == pytest.approx(1.0)  # still the start hour
    assert seam.weight(start + timedelta(minutes=30)) == pytest.approx(0.75)  # next clock hour
    assert seam.weight(start + timedelta(minutes=75)) == pytest.approx(0.75)


def test_decay_zero_keeps_a_constant_bias_up_to_the_seam():
    rows = _resolve(live_bias_seam_decay_hours=0.0)
    bias = (46 * 20.0 + 2 * 5.0) / 48
    assert _at(rows, 0)["price_buy"] == pytest.approx(bias)
    assert _at(rows, 6)["price_buy"] == pytest.approx(bias)


def test_seam_hours_without_a_price_fall_back_to_the_bias_and_log(caplog):
    rows = _resolve(live_bias_seam_hours=60)  # 60 h back reaches hours without a price
    bias = (46 * 20.0 + 2 * 5.0) / 48
    assert _at(rows, 0)["price_buy"] == pytest.approx(bias)
    assert "Anschluss" in caplog.text


def test_seam_anchor_is_capped():
    rows = _resolve(live_bias_cap_cent_kwh=3.0)
    assert _at(rows, 0)["price_buy"] == pytest.approx(3.0)


def test_live_path_fetches_only_hours_before_the_planning_start():
    """Without an SE feature frame, the horizon's own frame covers the known hours after the start."""
    target_frame = _feature_frame(PLANNING_START, SEAM + timedelta(hours=24))
    asked: list[list[datetime]] = []

    def _fetch(slots):
        asked.append(list(slots))
        return _feature_frame(SEAM - timedelta(hours=60), PLANNING_START)

    with patch("data.price_forecast_live.build_live_feature_frame_for_slots", side_effect=_fetch):
        rows = _resolve(forecast_feature_frame=target_frame, live_bias_feature_frame=None)
    assert len(asked) == 1
    assert max(asked[0]) < PLANNING_START
    assert len(asked[0]) == 46
    assert _at(rows, 0)["price_buy"] == pytest.approx(5.0)


def test_an_earlier_gap_does_not_move_the_midnight_seam():
    """Review 2026-11-28: one missing hour today put the seam there, and midnight jumped again."""
    market = [row for row in _market() if row["timestamp"] != SEAM - timedelta(hours=10)]
    target = [datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA) + timedelta(minutes=15 * i) for i in range(4 * 24)]
    frame = _feature_frame(SEAM - timedelta(hours=70), SEAM + timedelta(hours=24))
    rows = resolve_market_slots(
        market,
        target,
        missing_price_strategy="forecast",
        forecast_model=_zero_model(),
        forecast_feature_frame=frame,
        live_bias_enabled=True,
        live_bias_cap_cent_kwh=50.0,
        live_bias_feature_frame=frame,
    )
    by_utc = {row["slot_datetime"].astimezone(UTC): row for row in rows}
    gap = by_utc[(SEAM - timedelta(hours=10)).astimezone(UTC)]
    assert gap["price_source"] == PRICE_SOURCE_PREDICTED
    assert gap["price_buy"] == pytest.approx(20.0)  # its own seam: the 20 ct hours before it
    assert _at(by_utc, 0)["price_buy"] == pytest.approx(5.0)  # before the fix: 20 ct after 5 ct


def test_failed_past_feature_fetch_gives_no_bias_instead_of_a_shorter_window(caplog):
    """Review 2026-11-28: a failed fetch silently took the bias from the horizon hours only."""
    target_frame = _feature_frame(PLANNING_START, SEAM + timedelta(hours=24))
    with patch("data.price_forecast_live.build_live_feature_frame_for_slots", return_value=None):
        rows = _resolve(forecast_feature_frame=target_frame, live_bias_feature_frame=None)
    first = _at(rows, 0)
    assert first["price_buy"] == pytest.approx(0.0)  # model alone
    assert "live_bias_cent_kwh" not in first
    assert "Lookback-Stunden" in caplog.text


def test_aware_forecast_frame_merges_with_the_naive_past_frame():
    """Review 2026-11-28: concat of an aware horizon frame with the naive past frame raised."""
    naive = _feature_frame(PLANNING_START, SEAM + timedelta(hours=24))
    aware = naive.copy()
    aware.index = aware.index.tz_localize(VIENNA)

    def _fetch(slots):
        return _feature_frame(SEAM - timedelta(hours=60), PLANNING_START)

    with patch("data.price_forecast_live.build_live_feature_frame_for_slots", side_effect=_fetch):
        rows = _resolve(forecast_feature_frame=aware, live_bias_feature_frame=None)
    assert _at(rows, 0)["price_buy"] == pytest.approx(5.0)
    assert _at(rows, 8)["price_buy"] == pytest.approx((46 * 20.0 + 2 * 5.0) / 48)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("live_bias_seam_hours", 2.7),
        ("live_bias_seam_hours", True),
        ("live_bias_seam_decay_hours", float("nan")),
        ("live_bias_seam_decay_hours", True),
        ("live_bias_seam_decay_hours", "8"),
    ],
)
def test_seam_config_rejects_non_numbers(key, value):
    from data.price_forecast_live import get_live_bias_seam_decay_hours, get_live_bias_seam_hours

    getter = get_live_bias_seam_hours if key == "live_bias_seam_hours" else get_live_bias_seam_decay_hours
    with patch("config.Config._read_json_dict", return_value={"market_prices": {key: value}}):
        with pytest.raises(ValueError):
            getter()


def test_seam_anchor_weight_and_validation():
    start = SEAM.astimezone(UTC)
    seam = SeamAnchor(start=start, anchor_cent=2.0, decay_hours=8.0)
    assert seam.weight(start) == pytest.approx(1.0)
    assert seam.weight(start + timedelta(hours=2)) == pytest.approx(0.75)
    assert seam.weight(start + timedelta(hours=9)) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        SeamAnchor(start=start, anchor_cent=2.0, decay_hours=0.0)
    with pytest.raises(ValueError):
        SeamAnchor(start=start.replace(tzinfo=None), anchor_cent=2.0, decay_hours=8.0)


def test_ols_forecaster_rejects_a_seam_without_bias():
    seam = SeamAnchor(start=SEAM.astimezone(UTC), anchor_cent=2.0, decay_hours=8.0)
    with pytest.raises(ValueError):
        OlsForecaster(_zero_model(), _feature_frame(SEAM, SEAM + timedelta(hours=1)), tz=VIENNA, seam=seam)


def test_seam_config_getters_defaults_and_validation():
    from data.price_forecast_live import get_live_bias_seam_decay_hours, get_live_bias_seam_hours

    with patch("config.Config._read_json_dict", return_value={}):
        assert get_live_bias_seam_hours() == 2
        assert get_live_bias_seam_decay_hours() == pytest.approx(8.0)
    bad = {"market_prices": {"live_bias_seam_hours": 0, "live_bias_seam_decay_hours": -1}}
    with patch("config.Config._read_json_dict", return_value=bad):
        with pytest.raises(ValueError):
            get_live_bias_seam_hours()
        with pytest.raises(ValueError):
            get_live_bias_seam_decay_hours()
