"""normalize_scenario keeps enabled / own_reference flags for SE."""
from __future__ import annotations

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


def test_normalize_scenario_keeps_own_reference_bool():
    out = normalize_scenario(
        {
            "id": "x",
            "label": "X",
            "own_reference": True,
            "settings": {"battery_ids": ["b1"]},
        },
        0,
    )
    assert out["own_reference"] is True
    out_off = normalize_scenario(
        {
            "id": "y",
            "label": "Y",
            "own_reference": False,
            "settings": {"battery_ids": ["b1"]},
        },
        1,
    )
    assert out_off["own_reference"] is False
