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


def test_thermal_pulse_tight_prorates_below_full_calendar_sum(monkeypatch) -> None:
    """Tight-pulse fixture: prorated MILP day energy << sum of two full HDD days."""
    from data.modeled_climate import ModeledClimateContext
    from house_config.planning_flex_bridge import planning_thermal_to_milp
    from optimizer.thermal_flex_context import (
        _prorate_thermal_day_target_kwh,
        resolve_thermal_flex_contexts,
    )

    install_open_meteo_climate_mock(monkeypatch)
    profile = load_se_consumption_profile("thermal_pulse_tight")
    haus = next(c for c in profile["consumers"] if c["id"] == "haus")
    milp = planning_thermal_to_milp(haus)
    slots = window_slot_datetimes(_ANCHOR)
    matrix = [
        {
            "hour": slot.hour,
            "date": slot.date(),
            "slot_datetime": slot,
            "k_act": 10.0,
            "price_buy": 0.10,
            "expected_p_act": 0.5,
            "expected_p_pv": 0.0,
            "consumption_mode": "profile_spec",
        }
        for slot in slots
    ]
    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    daily = resolve_thermal_flex_contexts(
        matrix, [milp], profile, climate=climate
    )["haus"]["daily_targets"]
    assert len(daily) == 2
    full_sum = sum(float(v) for v in daily.values())
    prorated_sum = sum(
        _prorate_thermal_day_target_kwh(
            float(target),
            sum(1 for row in matrix if row["date"] == day),
        )
        for day, target in daily.items()
    )
    assert prorated_sum < full_sum * 0.9
    assert prorated_sum > 0.0


def test_thermal_pulse_tight_milp_feasible_with_ev(monkeypatch) -> None:
    """Regression dump shape: 1 kW Haus (max_on=16) + EV overnight stays Optimal."""
    from data.modeled_climate import ModeledClimateContext
    from house_config.planning_flex_bridge import (
        collect_planning_flex_consumers,
        resolve_profile_spec_flex_targets,
    )
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.charging_context import resolve_charging_contexts
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import (
        _add_consumer_delivery_constraints,
        filter_feasible_consumers,
    )
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import (
        add_thermal_flex_constraints,
        resolve_thermal_flex_contexts,
    )

    install_open_meteo_climate_mock(monkeypatch)
    profile = load_se_consumption_profile("thermal_pulse_tight")
    flex = collect_planning_flex_consumers(profile)
    assert {c["id"] for c in flex} == {"haus", "ev"}
    haus = next(c for c in flex if c["id"] == "haus")
    assert int(haus.get("max_on_quarterhours") or 0) == 16
    assert float(haus["nominal_power_kw"]) == pytest.approx(1.0)

    slots = window_slot_datetimes(_ANCHOR)
    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    targets = resolve_profile_spec_flex_targets(
        flex, profile, slots, window_end=_ANCHOR, climate=climate
    )
    matrix = [
        {
            "hour": slot.hour,
            "date": slot.date(),
            "slot_datetime": slot,
            "k_act": 10.0 if slot.hour >= 18 or slot.hour < 7 else 30.0,
            "price_buy": 0.10 if slot.hour >= 18 or slot.hour < 7 else 0.30,
            "expected_p_act": 0.5,
            "expected_p_pv": 0.0,
            "consumption_mode": "profile_spec",
            "charging_anchor": _ANCHOR,
        }
        for slot in slots
    ]
    contexts = resolve_charging_contexts(matrix, targets, consumers=flex)
    thermal_contexts = resolve_thermal_flex_contexts(
        matrix, flex, profile, climate=climate
    )
    remaining = {cid: float(targets.get(cid, 0.0)) for cid in ("haus", "ev")}
    battery = {
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "battery_capacity_kwh": 5.0,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers(
        flex, remaining, matrix, list(range(24)), False, contexts, {}
    )
    model = _build_milp_model(
        matrix, 24, battery, 50.0, planned, 0.0, remaining, {}
    )
    _add_milp_objective(model, matrix, 3.5, {}, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(
        model, matrix, remaining, list(range(24)), contexts, False
    )
    add_thermal_flex_constraints(
        model, matrix, list(range(24)), thermal_contexts
    )
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
