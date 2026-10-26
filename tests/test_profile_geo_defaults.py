"""Profile geo / PV defaults: only a missing value falls back; a real ``0`` is kept."""
from __future__ import annotations

import pytest

from house_config.profiles_store import _profile_geo_and_csv_fields as _geo_fields

_NETZ = {"netznutzung": {"area_id": "AT-VBG"}}


def _profile_geo_and_csv_fields(raw: dict) -> dict:
    return _geo_fields({**_NETZ, **raw})


@pytest.mark.parametrize(
    "key,default",
    [
        ("latitude", 48.0),
        ("longitude", 10.0),
        ("default_pv_tilt", 25.0),
        ("default_pv_azimuth", 0.0),
    ],
)
def test_zero_is_kept_and_missing_uses_default(key: str, default: float) -> None:
    assert _profile_geo_and_csv_fields({key: 0})[key] == 0.0
    assert _profile_geo_and_csv_fields({key: 0.0})[key] == 0.0
    for missing in ({}, {key: None}, {key: ""}):
        assert _profile_geo_and_csv_fields(missing)[key] == default


def test_non_numeric_value_fails_loud() -> None:
    with pytest.raises(ValueError, match="default_pv_tilt ungültig"):
        _profile_geo_and_csv_fields({"default_pv_tilt": "flach"})
