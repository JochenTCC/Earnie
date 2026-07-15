"""Tests für fixed-generic Grundlast-Overlay im Live-Pfad."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from data import profile_manager as pm


def _house_profile_with_fixed_kochen() -> dict:
    return {
        "id": "example_efh",
        "consumers": [
            {
                "id": "kochen",
                "label": "Kochen",
                "type": "generic",
                "nominal_power_kw": 2.0,
                "annual_kwh": 728.0,
                "schedule": {
                    "runs_per_week": 7,
                    "duration_h": 1.0,
                    "start_hour": 19,
                    "start_shift_h": 0.0,
                },
                "earnie_role": "known",
            },
            {
                "id": "fernsehen",
                "label": "Fernsehen",
                "type": "generic",
                "nominal_power_kw": 0.2,
                "annual_kwh": 364.0,
                "schedule": {
                    "runs_per_week": 7,
                    "duration_h": 5.0,
                    "start_hour": 19,
                    "start_shift_h": 12.0,
                },
                "earnie_role": "flex",
            },
        ],
    }


def test_fixed_generic_overlay_with_flexible_consumers_present():
    target_hours = [datetime(2026, 7, 15, h, 0) for h in range(24)]
    base = [0.5] * 24
    profile = _house_profile_with_fixed_kochen()
    raw_config = {"flexible_consumers": [{"id": "ev"}]}

    with patch.object(pm.config.CONFIG, "_raw_config", raw_config):
        with patch.object(
            pm.config,
            "get_resolved_runtime_settings",
            return_value={"_house_profile": profile},
        ):
            result = pm._apply_house_profile_baseload_overlay(target_hours, base)

    assert result[19] == 2.5
    assert result[18] == 0.5


def test_flexible_generic_not_added_to_grundlast_overlay():
    target_hours = [datetime(2026, 7, 15, h, 0) for h in range(24)]
    base = [0.5] * 24
    profile = _house_profile_with_fixed_kochen()
    raw_config = {"flexible_consumers": [{"id": "ev"}]}

    with patch.object(pm.config.CONFIG, "_raw_config", raw_config):
        with patch.object(
            pm.config,
            "get_resolved_runtime_settings",
            return_value={"_house_profile": profile},
        ):
            result = pm._apply_house_profile_baseload_overlay(target_hours, base)

    assert result[20] == 0.5
