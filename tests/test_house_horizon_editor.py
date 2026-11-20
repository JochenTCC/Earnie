"""SUSI P3a editor: axis and azimuth labels, directions the sun reaches, values of the bar component."""
from __future__ import annotations

from datetime import date

import pytest

from data.solar_horizon import HorizonProfile, sun_path
from ui import house_config_profile_horizon as editor


def _paths(latitude: float) -> dict[str, list[tuple[float, float]]]:
    return {
        label: sun_path(latitude, 9.7, date(2026, month, day))
        for label, month, day, _color in editor._SUN_DAYS
    }


def _labels(active: list[bool]) -> list[str]:
    return [label for label, on in zip(editor.DIRECTION_LABELS, active) if on]


def test_axis_runs_clockwise_from_north_and_is_labelled_like_the_pv_fields():
    assert editor.compass_deg(-180.0) == 0.0
    assert editor.compass_deg(-90.0) == 90.0
    assert editor.compass_deg(0.0) == 180.0
    assert editor.compass_deg(90.0) == 270.0
    labels = dict(zip(editor.DIRECTION_LABELS, map(editor.azimuth_label, editor.DIRECTION_AZIMUTHS)))
    assert labels["N"] == "±180°"
    assert labels["NNO"] == "-157,5°"
    assert labels["O"] == "-90°"
    assert labels["S"] == "0°"
    assert labels["W"] == "90°"


def test_mid_latitude_is_active_from_north_east_to_north_west():
    active = editor.active_directions(_paths(47.4))
    assert _labels(active) == list(editor.DIRECTION_LABELS[2:15])


def test_southern_hemisphere_leaves_the_south_inactive():
    active = editor.active_directions(_paths(-35.0))
    labels = _labels(active)
    assert "N" in labels and "O" in labels and "W" in labels
    assert "S" not in labels


def test_polar_site_has_every_direction_active():
    assert all(editor.active_directions(_paths(70.0)))


def test_seed_drops_stored_values_the_sun_never_reaches():
    active = editor.active_directions(_paths(47.4))
    stored = HorizonProfile(points=((-180.0, 20.0), (-157.5, 5.0), (0.0, 12.0)))
    seed = editor.seed_elevations(stored, active)
    assert seed[0] == 0.0 and seed[1] == 0.0
    assert seed[8] == 12.0
    assert editor.dropped_directions(stored, active)[:2] == ["N", "NNO"]
    assert editor.seed_elevations(None, active) == [0.0] * 16
    assert editor.dropped_directions(None, active) == []


def test_checked_elevations_zero_inactive_and_fail_loud():
    active = [False] + [True] * 15
    assert editor.checked_elevations([9.0] * 16, active) == [0.0] + [9.0] * 15
    with pytest.raises(ValueError, match="expected 16"):
        editor.checked_elevations([0.0] * 15, active)
    with pytest.raises(ValueError, match="out of range"):
        editor.checked_elevations([91.0] + [0.0] * 15, active)


def test_bar_key_has_no_double_underscore():
    assert "__" not in editor.horizon_bars_key("my__house")
