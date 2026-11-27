"""Stand-in of a country Energy-Charts publishes no data for (Denmark since 2026-11-04).

Live, a 404 for one country dropped the whole price forecast to the mirror. The sum of the
other countries is now scaled by the missing country's share; archive and training stay strict.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

from data import eu_market_features as emf
from data.eu_market_features import (
    EU_POWER_COLUMNS,
    GENERATION_COUNTRIES,
    MAX_STAND_IN_SHARE,
    CountryShares,
    EuPowerIncompleteError,
    compute_country_shares,
    fetch_eu_power_hourly,
    fetch_eu_power_hourly_with_stand_in,
    load_country_shares,
    save_country_shares,
)

VIENNA = ZoneInfo("Europe/Vienna")
DAY = date(2026, 11, 26)


def _http_error(status: int, country: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(
        f"{status} Client Error for url: https://api.energy-charts.info/public_power?country={country}",
        response=response,
    )


def _country_frame(day: date, value: float = 100.0) -> pd.DataFrame:
    hours = [datetime(day.year, day.month, day.day, h, tzinfo=VIENNA) for h in range(24)]
    return pd.DataFrame(
        {"wind_mw": value, "solar_mw": value, "load_mw": value, "residual_load_mw": value},
        index=pd.DatetimeIndex(hours, name="slot_datetime"),
    )


def _fetch_without(missing: dict[str, int]):
    def _fetch(country: str, start: date, end: date) -> pd.DataFrame:
        del end
        if country in missing:
            raise _http_error(missing[country], country)
        return _country_frame(start)

    return _fetch


def _uniform_shares(share_by_country: dict[str, float]) -> CountryShares:
    shares = {
        country: {
            base: [[share_by_country.get(country, 0.05)] * 24 for _m in range(12)]
            for base, _eu in EU_POWER_COLUMNS
        }
        for country in GENERATION_COUNTRIES
    }
    return CountryShares(range_start="2024-11-01", range_end="2025-11-01", shares=shares)


def test_country_without_data_is_stood_in_by_its_share(caplog):
    shares = _uniform_shares({"dk": 0.10})
    with patch.object(emf, "fetch_country_power_hourly", side_effect=_fetch_without({"dk": 404})):
        with caplog.at_level("WARNING", logger="data.eu_market_features"):
            frame, stand_in = fetch_eu_power_hourly_with_stand_in(DAY, DAY + timedelta(days=1), shares)

    assert stand_in == ("dk",)
    # 11 countries x 100 MW, scaled by 1 / (1 - 0.10)
    assert frame["eu_wind_mw"].iloc[0] == pytest.approx(1100.0 / 0.9)
    assert frame["eu_residual_load_mw"].iloc[12] == pytest.approx(1100.0 / 0.9)
    assert len(frame) == 24
    assert any("ohne dk" in r.getMessage() for r in caplog.records)


def _fetch_with_hours(hours_by_country: dict[str, range]):
    """Countries listed get only these Vienna hours (a response that just ends early)."""

    def _fetch(country: str, start: date, end: date) -> pd.DataFrame:
        del end
        frame = _country_frame(start)
        if country in hours_by_country:
            frame = frame.loc[[ts.hour in hours_by_country[country] for ts in frame.index]]
        return frame

    return _fetch


def test_country_data_ending_early_is_stood_in_for_the_missing_hours():
    """Denmark on 2026-11-04: values until 08:45, then nothing, and no error from the API."""
    shares = _uniform_shares({"dk": 0.10})
    with patch.object(emf, "fetch_country_power_hourly", side_effect=_fetch_with_hours({"dk": range(9)})):
        frame, stand_in = fetch_eu_power_hourly_with_stand_in(DAY, DAY + timedelta(days=1), shares)
    assert stand_in == ("dk",)
    assert frame["eu_wind_mw"].iloc[8] == pytest.approx(1200.0)
    assert frame["eu_wind_mw"].iloc[9] == pytest.approx(1100.0 / 0.9)


def test_archive_sum_fails_loud_on_a_gap_inside_the_day():
    with patch.object(emf, "fetch_country_power_hourly", side_effect=_fetch_with_hours({"dk": range(9)})):
        with pytest.raises(EuPowerIncompleteError, match=r"Land dk ohne Werte für 15 Stunde\(n\) ab 2026-11-26 09:00"):
            fetch_eu_power_hourly(DAY, DAY + timedelta(days=1))


def test_hour_outside_the_country_local_day_is_no_gap():
    """Energy-Charts returns Portugal's local day: 00:00 Vienna is never in it."""
    fetch = _fetch_with_hours({"pt": range(1, 24)})
    with patch.object(emf, "fetch_country_power_hourly", side_effect=fetch):
        strict = fetch_eu_power_hourly(DAY, DAY + timedelta(days=1))
        frame, stand_in = fetch_eu_power_hourly_with_stand_in(
            DAY, DAY + timedelta(days=1), _uniform_shares({})
        )
    assert stand_in == ()
    assert strict["eu_wind_mw"].iloc[0] == pytest.approx(1100.0)
    assert frame["eu_wind_mw"].iloc[0] == pytest.approx(1100.0)


def test_complete_data_needs_no_stand_in():
    with patch.object(emf, "fetch_country_power_hourly", side_effect=_fetch_without({})):
        frame, stand_in = fetch_eu_power_hourly_with_stand_in(
            DAY, DAY + timedelta(days=1), _uniform_shares({})
        )
    assert stand_in == ()
    assert frame["eu_wind_mw"].iloc[0] == pytest.approx(1200.0)


def test_stand_in_above_the_share_limit_fails_loud():
    shares = _uniform_shares({"de": 0.30})
    with patch.object(emf, "fetch_country_power_hourly", side_effect=_fetch_without({"de": 404})):
        with pytest.raises(EuPowerIncompleteError, match=r"Land de: keine Daten \(404\).*Grenze 15%"):
            fetch_eu_power_hourly_with_stand_in(DAY, DAY + timedelta(days=1), shares)


def test_rate_limit_is_not_stood_in_and_stops_at_that_country():
    """429 concerns the host, not the country: no stand-in, no further countries asked."""
    with patch.object(
        emf, "fetch_country_power_hourly", side_effect=_fetch_without({"de": 429})
    ) as fetch_mock:
        with pytest.raises(EuPowerIncompleteError, match="Land de fehlt"):
            fetch_eu_power_hourly_with_stand_in(DAY, DAY + timedelta(days=1), _uniform_shares({}))
    assert fetch_mock.call_count == 1


def test_archive_sum_stays_strict_on_a_country_without_data():
    """Archive (backtests, training) must not silently use a stood-in sum."""
    with patch.object(emf, "fetch_country_power_hourly", side_effect=_fetch_without({"dk": 404})):
        with pytest.raises(EuPowerIncompleteError, match="Land dk fehlt"):
            fetch_eu_power_hourly(DAY, DAY + timedelta(days=1))


def _year_frames(dk_wind: float) -> dict[str, pd.DataFrame]:
    index = pd.date_range("2025-01-01", "2025-12-31 23:00", freq="h", tz=VIENNA)
    frames = {}
    for country in GENERATION_COUNTRIES:
        wind = dk_wind if country == "dk" else 100.0
        solar = pd.Series([50.0 if 8 <= ts.hour <= 16 else 0.0 for ts in index], index=index)
        frames[country] = pd.DataFrame(
            {"wind_mw": wind, "solar_mw": solar, "load_mw": 1000.0, "residual_load_mw": 800.0},
            index=index,
        )
    return frames


def test_compute_country_shares_ratio_of_sums_and_zero_at_night():
    shares = compute_country_shares(
        _year_frames(dk_wind=110.0), range_start=date(2025, 1, 1), range_end=date(2026, 1, 1)
    )
    assert shares.share("dk", "wind_mw", 11, 3) == pytest.approx(110.0 / 1210.0, abs=1e-6)
    assert shares.share("de", "load_mw", 6, 12) == pytest.approx(1 / 12, abs=1e-6)
    assert shares.share("dk", "solar_mw", 1, 2) == 0.0  # night: no ratio
    assert shares.share("dk", "solar_mw", 1, 12) == pytest.approx(1 / 12, abs=1e-6)


def test_compute_country_shares_needs_every_month():
    frames = {c: f.loc[f.index.month != 7] for c, f in _year_frames(100.0).items()}
    with pytest.raises(ValueError, match="Monate"):
        compute_country_shares(frames, range_start=date(2025, 1, 1), range_end=date(2026, 1, 1))


def test_country_shares_round_trip(tmp_path: Path):
    shares = compute_country_shares(
        _year_frames(dk_wind=110.0), range_start=date(2025, 1, 1), range_end=date(2026, 1, 1)
    )
    path = tmp_path / "shares.json"
    save_country_shares(shares, path)
    loaded = load_country_shares(path)
    assert loaded.share("dk", "wind_mw", 3, 5) == shares.share("dk", "wind_mw", 3, 5)
    assert path.read_bytes().count(b"\r\n") == 0


def test_shipped_country_shares_stand_in_denmark():
    """The shipped shares cover every country; Denmark stays below the stand-in limit."""
    shares = load_country_shares()
    for base, _eu in EU_POWER_COLUMNS:
        for month in range(1, 13):
            for hour in range(24):
                assert abs(shares.share("dk", base, month, hour)) <= MAX_STAND_IN_SHARE
