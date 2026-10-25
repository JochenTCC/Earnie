"""Coverage for data.data_loader market-price load paths (offline mocks)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from data import data_loader as dl


def _price_frame(start: str = "2024-06-01 00:00:00", hours: int = 24) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="h")
    return pd.DataFrame({"price_cent_kwh": [10.0] * hours}, index=idx)


def test_ensure_csv_exists_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Preis-CSV fehlt"):
        dl._ensure_csv_exists(str(tmp_path / "missing.csv"))


def test_last_complete_month_end_on_month_end():
    assert dl.last_complete_month_end(pd.Timestamp("2024-06-30")) == pd.Timestamp(
        "2024-06-30"
    )


def test_last_complete_month_end_mid_month():
    assert dl.last_complete_month_end(pd.Timestamp("2024-06-15")) == pd.Timestamp(
        "2024-05-31"
    )


def test_prices_to_dataframe_converts_eur_mwh():
    ts = pd.Series(
        [
            pd.Timestamp("2024-06-01 00:00:00", tz="UTC"),
            pd.Timestamp("2024-06-01 01:00:00", tz="UTC"),
        ]
    )
    frame = dl._prices_to_dataframe(ts, pd.Series([100.0, 200.0]))
    assert float(frame.loc[pd.Timestamp("2024-06-01 02:00:00"), "price_cent_kwh"]) == pytest.approx(
        10.0
    )


def test_fetch_awattar_prices_parses_payload():
    start = pd.Timestamp("2024-06-01")
    end = pd.Timestamp("2024-06-01")
    payload = {
        "data": [
            {
                "start_timestamp": int(start.tz_localize("Europe/Vienna").timestamp() * 1000),
                "marketprice": 100.0,
            }
        ]
    }
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    with patch("data.data_loader.requests.get", return_value=response):
        frame = dl.fetch_awattar_prices(start, end, "https://example.test/awattar")
    assert not frame.empty
    assert float(frame.iloc[0]["price_cent_kwh"]) == pytest.approx(10.0)


def test_fetch_awattar_prices_empty_payload_raises():
    response = MagicMock()
    response.json.return_value = {"data": []}
    response.raise_for_status = MagicMock()
    with patch("data.data_loader.requests.get", return_value=response):
        with pytest.raises(ValueError, match="keine Preisdaten"):
            dl.fetch_awattar_prices(
                pd.Timestamp("2024-06-01"),
                pd.Timestamp("2024-06-01"),
                "https://example.test/awattar",
            )


def test_fetch_api_prices_qh_first_falls_back_to_awattar():
    fallback = _price_frame()
    with patch.object(
        dl, "fetch_energy_charts_prices", side_effect=requests.Timeout("boom")
    ):
        with patch.object(dl, "fetch_awattar_prices", return_value=fallback) as awattar:
            out = dl._fetch_api_prices_qh_first(
                zone="AT",
                start=pd.Timestamp("2024-06-01"),
                end=pd.Timestamp("2024-06-01"),
                awattar_url="https://example.test/awattar",
                timeout=5,
            )
    assert out is fallback
    awattar.assert_called_once()


def test_load_market_prices_api_at_zone(monkeypatch):
    frame = _price_frame()
    monkeypatch.setattr(dl, "_fetch_api_prices_qh_first", lambda **_k: frame)
    out = dl.load_market_prices(
        pd.Timestamp("2024-06-01"),
        pd.Timestamp("2024-06-01"),
        {"price_source": "api", "energy_charts_bzn": "AT"},
        awattar_url="https://example.test/awattar",
    )
    assert len(out) == 24


def test_load_market_prices_api_unknown_zone_raises():
    with pytest.raises(ValueError, match="Unbekannte Marktzone"):
        dl.load_market_prices(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"price_source": "api"},
            awattar_url="https://example.test/awattar",
            market_zone="XX",
        )


def test_load_market_prices_csv_requires_path():
    with pytest.raises(ValueError, match="path_price"):
        dl.load_market_prices(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"price_source": "csv"},
            awattar_url="https://example.test/awattar",
        )


def test_load_market_prices_csv_file(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "Datum (MEZ),Day Ahead Auktion (DE-LU)\n"
        "unit,EUR/MWh\n"
        "2024-06-01T00:00:00Z,100.0\n"
        "2024-06-01T01:00:00Z,110.0\n",
        encoding="utf-8",
    )
    out = dl.load_market_prices(
        pd.Timestamp("2024-06-01"),
        pd.Timestamp("2024-06-01"),
        {"price_source": "csv", "path_price": str(csv_path)},
        awattar_url="https://example.test/awattar",
    )
    assert len(out) == 2
    assert float(out.iloc[0]["price_cent_kwh"]) == pytest.approx(10.0)


def _write_zone_csv(path, zone):
    path.write_text(
        f"Datum (MEZ),Day Ahead Auktion ({zone})\n"
        "unit,EUR/MWh\n"
        "2024-06-01T00:00:00Z,100.0\n",
        encoding="utf-8",
    )


def test_load_market_prices_csv_reads_column_of_market_zone(tmp_path):
    csv_path = tmp_path / "prices.csv"
    _write_zone_csv(csv_path, "AT")
    out = dl.load_market_prices(
        pd.Timestamp("2024-06-01"),
        pd.Timestamp("2024-06-01"),
        {"price_source": "csv", "path_price": str(csv_path)},
        awattar_url="https://example.test/awattar",
        market_zone="AT",
    )
    assert float(out.iloc[0]["price_cent_kwh"]) == pytest.approx(10.0)


def test_load_market_prices_csv_zone_column_missing_fails_loud(tmp_path):
    csv_path = tmp_path / "prices.csv"
    _write_zone_csv(csv_path, "DE-LU")
    with pytest.raises(ValueError, match=r"Day Ahead Auktion \(AT\)"):
        dl.load_market_prices(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"price_source": "csv", "path_price": str(csv_path)},
            awattar_url="https://example.test/awattar",
            market_zone="AT",
        )


def test_load_market_prices_for_scenario_uses_zone():
    frame = _price_frame()
    with patch.object(dl, "load_market_prices", return_value=frame) as loaded:
        out = dl.load_market_prices_for_scenario(
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-01"),
            {"market_zone": "CH"},
            {"price_source": "api"},
            awattar_url="https://example.test/awattar",
        )
    assert out is frame
    assert loaded.call_args.kwargs["market_zone"] == "CH"


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
