"""Battery SoC window: ``battery_min_soc`` must be strictly below ``battery_max_soc``."""
from __future__ import annotations

import pytest

from house_config.entity_resolution import normalize_battery


def _raw(min_soc: float, max_soc: float) -> dict:
    return {
        "id": "b1",
        "inverter_id": "wr_main",
        "battery_capacity_kwh": 10.0,
        "battery_max_power_kw": 5.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": min_soc,
        "battery_max_soc": max_soc,
        "regulates_on": "grid",
        "battery_wear": {"enabled": False},
    }


def test_valid_soc_window_is_kept() -> None:
    spec = normalize_battery(_raw(10.0, 90.0), 0)
    assert (spec["battery_min_soc"], spec["battery_max_soc"]) == (10.0, 90.0)


@pytest.mark.parametrize("min_soc,max_soc", [(10.0, 5.0), (50.0, 50.0)])
def test_soc_window_must_have_min_below_max(min_soc: float, max_soc: float) -> None:
    with pytest.raises(ValueError, match="battery_min_soc .* kleiner als battery_max_soc"):
        normalize_battery(_raw(min_soc, max_soc), 0)
