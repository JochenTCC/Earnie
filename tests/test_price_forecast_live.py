"""Tests für Live-Preisprognose-Config und resolve_market_slots-Kwargs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.price_forecast_live import (
    DEFAULT_MODEL_PATH,
    MISSING_PRICE_STRATEGY_FORECAST,
    MISSING_PRICE_STRATEGY_MIRROR,
    _archive_covers_slot_range,
    build_live_feature_frame_for_slots,
    get_forecast_model_path,
    get_missing_price_strategy,
    resolve_market_slots_kwargs,
)


def test_get_missing_price_strategy_defaults_to_forecast_without_block():
    with patch(
        "config.Config._read_json_dict",
        return_value={},
    ):
        assert get_missing_price_strategy() == MISSING_PRICE_STRATEGY_FORECAST


def test_get_missing_price_strategy_reads_mirror_from_config(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"market_prices": {"missing_price_strategy": "mirror"}}),
        encoding="utf-8",
    )
    with patch("config.CONFIG_JSON_PATH", config_path):
        with patch(
            "config.Config._read_json_dict",
            return_value=json.loads(config_path.read_text(encoding="utf-8")),
        ):
            assert get_missing_price_strategy() == MISSING_PRICE_STRATEGY_MIRROR


def test_resolve_market_slots_kwargs_mirror_only():
    with patch(
        "data.price_forecast_live.get_missing_price_strategy",
        return_value=MISSING_PRICE_STRATEGY_MIRROR,
    ):
        kwargs = resolve_market_slots_kwargs([])
    assert kwargs == {"missing_price_strategy": MISSING_PRICE_STRATEGY_MIRROR}


def test_resolve_market_slots_kwargs_forecast_without_model_falls_back_to_mirror():
    with patch(
        "data.price_forecast_live.get_missing_price_strategy",
        return_value=MISSING_PRICE_STRATEGY_FORECAST,
    ):
        with patch("data.price_forecast_live.load_configured_model", return_value=None):
            with patch("data.price_forecast_live.get_forecast_model_path") as path_mock:
                path_mock.return_value = Path("data/cache/missing.json")
                kwargs = resolve_market_slots_kwargs([])
    assert kwargs["missing_price_strategy"] == MISSING_PRICE_STRATEGY_MIRROR


def test_get_forecast_model_path_resolves_runtime_prefix(monkeypatch, tmp_path):
    nas_runtime = tmp_path / "nas_runtime"
    nas_runtime.mkdir()
    model_file = nas_runtime / "price_model_coefficients.json"
    model_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(nas_runtime))

    with patch(
        "config.Config._read_json_dict",
        return_value={
            "market_prices": {
                "forecast_model_path": "runtime/price_model_coefficients.json",
            }
        },
    ):
        resolved = get_forecast_model_path()
        assert resolved == model_file
        assert resolved.exists()


def test_get_forecast_model_path_falls_back_to_share_default(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    share_model = Path("share/data/price_model_coefficients.json")
    if not share_model.exists():
        pytest.skip("shipped share model missing in workspace")
    with patch(
        "config.Config._read_json_dict",
        return_value={
            "market_prices": {"forecast_model_path": str(missing)},
        },
    ):
        resolved = get_forecast_model_path()
    assert resolved == DEFAULT_MODEL_PATH
    assert resolved.exists()


def test_archive_covers_slot_range_false_for_future_slot():
    tz = ZoneInfo("Europe/Vienna")
    future_slot = datetime(2099, 1, 1, 12, tzinfo=tz)
    assert _archive_covers_slot_range([future_slot]) is False


def test_build_live_feature_frame_uses_forecast_path_for_future_slots():
    from data import price_forecast_live as pfl

    pfl._live_feature_cache.clear()
    pfl._power_day_cache.clear()
    tz = ZoneInfo("Europe/Vienna")
    future_slot = datetime(2099, 1, 1, 12, tzinfo=tz)
    fake = pd.DataFrame(
        {
            "eu_wind_mw": [1.0],
            "eu_solar_mw": [2.0],
            "eu_load_mw": [3.0],
            "eu_residual_load_mw": [4.0],
            "eu_wind_speed_kmh": [5.0],
            "eu_shortwave_radiation_wm2": [6.0],
            "hour_sin": [0.0],
            "hour_cos": [1.0],
            "weekday": [0],
            "month": [1],
        },
        index=pd.DatetimeIndex([future_slot.replace(tzinfo=None)]),
    )
    with patch(
        "data.price_forecast_live._build_forecast_feature_frame",
        return_value=fake,
    ) as forecast_mock:
        with patch(
            "data.price_forecast_live._build_archive_feature_frame"
        ) as archive_mock:
            result = build_live_feature_frame_for_slots([future_slot])
    assert result is not None
    forecast_mock.assert_called_once()
    archive_mock.assert_not_called()


def test_resolve_market_slots_kwargs_forecast_without_features_uses_mirror():
    model = object()
    with patch(
        "data.price_forecast_live.get_missing_price_strategy",
        return_value=MISSING_PRICE_STRATEGY_FORECAST,
    ):
        with patch("data.price_forecast_live.load_configured_model", return_value=model):
            with patch(
                "data.price_forecast_live.build_live_feature_frame_for_slots",
                return_value=None,
            ):
                kwargs = resolve_market_slots_kwargs([])
    assert kwargs["missing_price_strategy"] == MISSING_PRICE_STRATEGY_MIRROR
    assert "forecast_model" not in kwargs


def test_build_live_feature_frame_logs_error_on_forecast_failure(caplog):
    from data import price_forecast_live as pfl

    pfl._live_feature_cache.clear()
    pfl._power_day_cache.clear()
    tz = ZoneInfo("Europe/Vienna")
    future_slot = datetime(2099, 1, 1, 12, tzinfo=tz)
    with patch(
        "data.price_forecast_live._build_forecast_feature_frame",
        side_effect=ValueError("boom"),
    ):
        with caplog.at_level("WARNING", logger="data.price_forecast_live"):
            assert build_live_feature_frame_for_slots([future_slot]) is None
    assert any("EU-Features nicht ladbar" in r.message for r in caplog.records)


def test_feature_load_error_summary_omits_url():
    from data.price_forecast_live import _feature_load_error_summary
    import requests

    response = requests.Response()
    response.status_code = 400
    exc = requests.HTTPError("https://example.com/long-url", response=response)
    assert _feature_load_error_summary(exc) == "HTTP 400"
