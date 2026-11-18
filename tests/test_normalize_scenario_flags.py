"""normalize_scenario keeps the enabled flag for SE; own_reference is gone."""
from __future__ import annotations

import pytest

from settings.scenarios import normalize_scenario


def test_normalize_scenario_defaults_enabled_true():
    out = normalize_scenario(
        {"id": "live", "label": "Live", "settings": {"battery_ids": ["b1"]}},
        0,
    )
    assert out["enabled"] is True
    assert "own_reference" not in out


def test_normalize_scenario_keeps_enabled_false():
    out = normalize_scenario(
        {
            "id": "off",
            "label": "Off",
            "enabled": False,
            "settings": {"battery_ids": ["b1"]},
        },
        0,
    )
    assert out["enabled"] is False


def test_normalize_scenario_rejects_own_reference():
    """Removed by dm6.scenario_own_reference_removal: a leftover fails loud."""
    with pytest.raises(ValueError, match="own_reference"):
        normalize_scenario(
            {"id": "x", "label": "X", "own_reference": True, "settings": {"battery_ids": ["b1"]}},
            0,
        )
