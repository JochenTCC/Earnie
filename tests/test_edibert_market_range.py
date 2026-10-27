"""SE / backtesting market prices through Edibert's archive (Edibert P4b)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from edibert import api

from data import edibert_market_range as emr

API_CFG = {"price_source": "api"}


class _EnergyCharts:
    """Fake Edibert ``http_get`` for Energy-Charts: EUR/MWh = 100 × UTC hour of the slot."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, url, params, timeout):
        self.calls.append(dict(params))
        if self.fail:
            raise api.MarketSourceError("Energy-Charts down")
        first = datetime.fromisoformat(params["start"]).replace(tzinfo=UTC)
        last = datetime.fromisoformat(params["end"]).replace(tzinfo=UTC)
        stamps, prices = [], []
        slot = first
        while slot < last:
            stamps.append(int(slot.timestamp()))
            prices.append(100.0 * slot.hour)
            slot += timedelta(minutes=15)
        return json.dumps({"unix_seconds": stamps, "price": prices})


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    web = _EnergyCharts()
    monkeypatch.setattr("edibert.market.archive.http_get", web)
    return {"web": web, "dir": tmp_path}


def test_api_prices_in_vienna_time_with_the_autumn_hour_averaged(archive):
    day = pd.Timestamp("2025-10-26")
    out = emr.load_market_prices(day, day, API_CFG, market_zone="AT")

    assert len(out) == 24 * 4  # 25 hours, the repeated 02:00 hour folded into one
    assert out.index[0] == pd.Timestamp("2025-10-26 00:00")
    # 00:00 local = 22:00 UTC the day before
    assert out.loc[pd.Timestamp("2025-10-26 00:00"), "price_cent_kwh"] == pytest.approx(220.0)
    # 02:15 local exists twice (00:15 and 01:15 UTC): mean of 0 and 10 cent
    assert out.loc[pd.Timestamp("2025-10-26 02:15"), "price_cent_kwh"] == pytest.approx(5.0)
    assert archive["web"].calls[0]["bzn"] == "AT"


def test_a_cached_month_is_not_asked_again(archive):
    day = pd.Timestamp("2025-06-10")
    first = emr.load_market_prices(day, day, API_CFG, market_zone="DE-LU")
    again = emr.load_market_prices(day, day + pd.Timedelta(days=1), API_CFG, market_zone="DE-LU")

    assert len(archive["web"].calls) == 1
    assert (archive["dir"] / "edibert_market" / "market_archive" / "DE-LU" / "2025-06.json").is_file()
    pd.testing.assert_frame_equal(first, again.iloc[: len(first)])


def test_zone_falls_back_to_the_configured_bidding_zone(archive):
    day = pd.Timestamp("2025-06-10")
    emr.load_market_prices(day, day, {**API_CFG, "energy_charts_bzn": "CH"})
    assert archive["web"].calls[0]["bzn"] == "CH"


def test_no_zone_at_all_fails_loud(archive):
    with pytest.raises(ValueError, match="Keine Marktzone"):
        emr.load_market_prices(pd.Timestamp("2025-06-10"), pd.Timestamp("2025-06-10"), API_CFG)


def test_no_answer_and_no_cache_fails_loud_without_awattar(archive):
    archive["web"].fail = True
    with pytest.raises(api.EdibertError) as exc:
        emr.load_market_prices(
            pd.Timestamp("2025-06-10"), pd.Timestamp("2025-06-10"), API_CFG, market_zone="AT"
        )
    assert exc.value.code == api.ErrorCode.MARKET_DATA_UNAVAILABLE


def _write_zone_csv(path, zone: str) -> None:
    path.write_text(
        f"Datum (MEZ),Day Ahead Auktion ({zone})\n"
        "utc,EUR/MWh\n"
        "2024-06-01T00:00:00Z,100.0\n"
        "2024-06-01T01:00:00Z,110.0\n",
        encoding="utf-8",
    )


def test_csv_reads_the_column_of_the_market_zone(tmp_path):
    csv_path = tmp_path / "prices.csv"
    _write_zone_csv(csv_path, "AT")
    out = emr.load_market_prices(
        pd.Timestamp("2024-06-01"),
        pd.Timestamp("2024-06-01"),
        {"price_source": "csv", "path_price": str(csv_path)},
        market_zone="AT",
    )
    assert len(out) == 2
    assert out.index[0] == pd.Timestamp("2024-06-01 02:00")
    assert float(out.iloc[0]["price_cent_kwh"]) == pytest.approx(10.0)


def test_csv_without_the_zone_column_fails(tmp_path):
    csv_path = tmp_path / "prices.csv"
    _write_zone_csv(csv_path, "DE-LU")
    with pytest.raises(ValueError, match=r"Day Ahead Auktion \(AT\)"):
        emr.load_market_prices(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"price_source": "csv", "path_price": str(csv_path)},
            market_zone="AT",
        )


def test_csv_requires_a_path():
    with pytest.raises(ValueError, match="path_price"):
        emr.load_market_prices(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"price_source": "csv"},
            market_zone="AT",
        )


def test_csv_file_must_exist(tmp_path):
    with pytest.raises(FileNotFoundError, match="Preis-CSV fehlt"):
        emr.load_market_prices(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"price_source": "csv", "path_price": str(tmp_path / "missing.csv")},
            market_zone="AT",
        )
