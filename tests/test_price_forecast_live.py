"""Tests für Live-Preisprognose-Config und resolve_market_slots-Kwargs."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from data.price_forecast_live import (
    MISSING_PRICE_STRATEGY_FORECAST,
    MISSING_PRICE_STRATEGY_MIRROR,
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
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(nas_runtime))

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
