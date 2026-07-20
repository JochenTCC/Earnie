"""Invariant: profile_spec window kWh ≈ hourly Historisch-style load (mini profiles)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from house_config.consumption_csv import write_canonical_hourly_csv
from house_config.planning_flex_bridge import (
    collect_planning_flex_consumers,
    house_profile_baseload_overlay,
    milp_flex_thermal_annual_ids,
    profile_flat_baseload_kw,
    profile_reference_hourly_load,
    resolve_profile_spec_flex_targets,
)
from simulation.engine import window_slot_datetimes
from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock
from tests.fixtures.se_consumption import PROFILE_IDS, load_se_consumption_profile

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

# Sunset-style anchor (overnight EV / thermal windows).
_ANCHOR = datetime(2025, 3, 1, 7, 0)
_ABS_TOL_KWH = 0.05


def _profile_spec_window_kwh(
    profile: dict,
    slots: list[datetime],
    *,
    climate,
    window_end: datetime,
) -> float:
    flex = collect_planning_flex_consumers(profile)
    thermal_milp = milp_flex_thermal_annual_ids(flex)
    flat = profile_flat_baseload_kw(profile)
    overlay = house_profile_baseload_overlay(
        profile,
        slots,
        historical_totals=None,
        cons_data_consumer_ids=set(),
        milp_flex_thermal_ids=thermal_milp,
        climate=climate,
    )
    baseload = sum(flat + extra for extra in overlay)
    targets = resolve_profile_spec_flex_targets(
        flex,
        profile,
        slots,
        window_end=window_end,
        climate=climate,
    )
    return round(baseload + sum(targets.values()), 3)


def _hourly_window_kwh(profile: dict, slots: list[datetime], *, climate) -> float:
    return round(sum(profile_reference_hourly_load(profile, slots, climate=climate)), 3)


def _attach_csv_thermal(profile: dict, tmp_path: Path, slots: list[datetime]) -> dict:
    """Fill empty profile_csv on mixed_csv_thermal with a flat series covering the window."""
    start = slots[0] - timedelta(hours=24)
    hours = len(slots) + 48
    path = tmp_path / "swimspa_window.csv"
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 2.5)
        for i in range(hours)
    ]
    write_canonical_hourly_csv(str(path), rows)
    consumers = []
    for consumer in profile["consumers"]:
        if consumer.get("id") == "swimspa":
            consumers.append(
                {
                    **consumer,
                    "use_profile_csv": True,
                    "profile_csv": str(path),
                }
            )
        else:
            consumers.append(consumer)
    return {**profile, "consumers": consumers}


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_profile_spec_matches_hourly_reference_load(
    profile_id: str, tmp_path: Path, monkeypatch
) -> None:
    """SE Jahres Verbrauch family: spec window total must match hourly model."""
    install_open_meteo_climate_mock(monkeypatch)
    from data.modeled_climate import ModeledClimateContext

    profile = load_se_consumption_profile(profile_id)
    slots = window_slot_datetimes(_ANCHOR)
    if profile_id == "mixed_csv_thermal":
        profile = _attach_csv_thermal(profile, tmp_path, slots)

    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    spec_kwh = _profile_spec_window_kwh(
        profile, slots, climate=climate, window_end=_ANCHOR
    )
    hourly_kwh = _hourly_window_kwh(profile, slots, climate=climate)
    assert spec_kwh == pytest.approx(hourly_kwh, abs=_ABS_TOL_KWH), (
        f"{profile_id}: profile_spec={spec_kwh} hourly={hourly_kwh}"
    )


def test_ev_power_capped_is_below_uncapped_soc() -> None:
    """Fixture documents the regression shape: modeled << SOC-only daily."""
    from house_config.ev_profile import ev_daily_kwh
    from house_config.planning_flex_bridge import _consumer_window_kwh

    profile = load_se_consumption_profile("ev_power_capped")
    ev = next(c for c in profile["consumers"] if c["id"] == "ev")
    slots = window_slot_datetimes(_ANCHOR)
    modeled = _consumer_window_kwh(ev, slots)
    soc = ev_daily_kwh(ev, _ANCHOR.date())
    assert modeled == pytest.approx(13.0)
    assert modeled < soc
