"""thermal_annual / EV normalization: ``0`` is kept where valid, invalid persons fail loud."""
from __future__ import annotations

import pytest

from house_config.profiles_thermal_annual import _build_thermal_block, int_or_default


def test_int_or_default_keeps_zero() -> None:
    assert int_or_default(0, 4) == 0
    assert int_or_default("0", 4) == 0
    for missing in (None, ""):
        assert int_or_default(missing, 4) == 4


def test_persons_default_and_value() -> None:
    assert _build_thermal_block({})["persons"] == 2
    assert _build_thermal_block({"persons": 4})["persons"] == 4


@pytest.mark.parametrize("persons", [0, -1])
def test_persons_below_one_fails_loud(persons: int) -> None:
    with pytest.raises(ValueError, match="persons muss >= 1 sein"):
        _build_thermal_block({"persons": persons})


def test_flat_solar_collector_tilt_is_kept() -> None:
    assert _build_thermal_block({"solar_thermal_tilt_deg": 0})["solar_thermal_tilt_deg"] == 0.0
    assert _build_thermal_block({})["solar_thermal_tilt_deg"] == 18.0
