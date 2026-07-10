# tests/test_consumption_display_integration.py
"""Integrationstests für Verbrauchs-UI in drei Seiten (1.25.b)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

from ui.consumption_comparison_panel import render_consumption_comparison_panel
from ui.consumption_display import ConsumptionDisplayMode
from ui.consumption_display.adapters import bundle_from_cons_data, bundle_from_csv_validation
from ui.scenario_runtime_form import render_runtime_scenario_form


def _sample_profile() -> dict:
    return {
        "annual_kwh": 120.0,
        "baseload_kwh": 48.0,
        "consumers": [{"id": "pool", "type": "generic", "annual_kwh": 72.0}],
    }


def test_csv_validation_bundle_from_house_config_inputs():
    series = [
        ("2023-01-01 00:00:00", 2.0),
        ("2023-01-01 01:00:00", 3.0),
    ]
    bundle = bundle_from_csv_validation(series, _sample_profile())
    assert bundle.actual_total == [2.0, 3.0]
    assert "pool" in bundle.consumer_series
    assert bundle.baseload == [24.0, 24.0]


def test_cons_data_bundle_for_backtesting_section():
    idx = pd.date_range("2024-01-01", periods=3, freq="h", name="timestamp")
    df = pd.DataFrame(
        {
            "total_kw": [3.0, 3.0, 3.0],
            "baseload_kw": [1.0, 1.0, 1.0],
            "pv_kw": [0.5, 1.0, 0.0],
            "pool_kw": [2.0, 2.0, 2.0],
        },
        index=idx,
    )
    bundle = bundle_from_cons_data(df)
    assert bundle.pv is not None
    assert bundle.actual_total is None


def test_legacy_panel_delegates_to_csv_validation_mode():
    series = [("2023-01-01 00:00:00", 1.0)]
    profile = _sample_profile()
    with patch("ui.consumption_comparison_panel.render_consumption_display") as mock_render:
        render_consumption_comparison_panel(
            actual_monthly={"2023-01": 1.0},
            modeled_profile=profile,
            series=series,
            key_prefix="legacy_test",
        )
    mock_render.assert_called_once()
    assert mock_render.call_args.args[0] == ConsumptionDisplayMode.CSV_VALIDATION


def test_runtime_form_imports_consumption_display():
    assert ConsumptionDisplayMode.MODELED_PROFILE.value == "modeled_profile"
    assert callable(render_runtime_scenario_form)
