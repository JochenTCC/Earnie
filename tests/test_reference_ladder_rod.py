"""L2: a heating rod beside a fuel source runs on the export left at the meter (spec § 4.3)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from optimizer.rod_store import STORE_BALANCE_CONTEXT_KEY, RodStoreBalance
from optimizer.sim_baseline import (
    DEFAULT_RULE_PARAMS,
    SURPLUS_BATTERY_FIRST,
    SurplusRod,
    _simulate_single_hour_baseline,
    build_rule_based_flex_kw_per_hour,
)
from optimizer.slot_duration import DEFAULT_DT_H
from simulation import heat_fuel, reference_ladder

DAY = date(2025, 6, 2)
START = datetime(2025, 6, 2, 0, 0)
SLOTS = 8
ROD_KW = 2.0
ROD_SLOT_KWH = ROD_KW * DEFAULT_DT_H
NO_BATTERY = {
    "battery_capacity_kwh": 0.0,
    "max_power_kw": 0.0,
    "efficiency": 1.0,
    "min_soc": 0.0,
    "max_soc": 100.0,
    "standby_power_kw": 0.0,
}
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 2.0,
    "efficiency": 1.0,
    "min_soc": 0.0,
    "max_soc": 100.0,
    "standby_power_kw": 0.0,
}
EV = {"id": "ev", "type": "ev", "nominal_power_kw": 3.0}


def _matrix(pv_kw: float, load_kw: float = 0.5) -> list[dict]:
    return [
        {
            "slot_datetime": START + timedelta(minutes=15 * t),
            "date": DAY,
            "expected_p_pv": pv_kw,
            "expected_p_act": load_kw,
            "k_act": 20.0,
            "k_push_act": 6.5,
            "price_buy": 10.0,
        }
        for t in range(SLOTS)
    ]


def _rod(*, heat_kwh: float = 100.0, eligible: list[int] | None = None) -> SurplusRod:
    return SurplusRod(
        cid="rod",
        nominal_kw=ROD_KW,
        eligible=list(range(SLOTS)) if eligible is None else eligible,
        balance=RodStoreBalance(capacity_kwh=heat_kwh, start_kwh=0.0, drain_kwh=[1e-6] * SLOTS),
        level_kwh=0.0,
    )


def _run(
    matrix: list[dict],
    rod: SurplusRod,
    *,
    battery: dict = NO_BATTERY,
    soc: float = 50.0,
    consumers: list[dict] | None = None,
    targets: dict[str, float] | None = None,
    params: dict = DEFAULT_RULE_PARAMS,
) -> list[dict[str, float]]:
    consumers = consumers or []
    prices = {row["slot_datetime"]: 20.0 for row in matrix}
    return build_rule_based_flex_kw_per_hour(
        matrix,
        targets or {},
        {c["id"]: list(range(SLOTS)) for c in consumers},
        consumers,
        {c["id"]: [1.0] * SLOTS for c in consumers},
        prices,
        params,
        book_indices=list(range(SLOTS)),
        battery_params=battery,
        initial_soc=soc,
        surplus_rods=[rod],
    ).per_slot


def _rod_kw(per_slot: list[dict[str, float]]) -> list[float]:
    return [slot["rod"] for slot in per_slot]


def test_no_surplus_no_rod() -> None:
    assert _rod_kw(_run(_matrix(pv_kw=0.5), _rod())) == [0.0] * SLOTS


def test_export_below_nominal_power_does_not_start_it() -> None:
    assert _rod_kw(_run(_matrix(pv_kw=0.5 + ROD_KW - 0.01), _rod())) == [0.0] * SLOTS


def test_it_runs_at_nominal_power_on_enough_export() -> None:
    assert _rod_kw(_run(_matrix(pv_kw=0.5 + ROD_KW), _rod())) == [ROD_KW] * SLOTS


def test_the_store_caps_it_and_no_slot_runs_in_part() -> None:
    per_slot = _run(_matrix(pv_kw=5.0), _rod(heat_kwh=2.5 * ROD_SLOT_KWH))
    assert _rod_kw(per_slot) == [ROD_KW, ROD_KW] + [0.0] * (SLOTS - 2)


def test_it_stays_outside_its_window() -> None:
    assert _rod_kw(_run(_matrix(pv_kw=5.0), _rod(eligible=[3]))) == [0.0, 0.0, 0.0, ROD_KW] + [0.0] * 4


def test_the_battery_comes_first_and_keeps_its_charge() -> None:
    """Surplus 3 kW, the battery takes 2 kW: 1 kW is left, too little for a 2 kW rod."""
    assert _rod_kw(_run(_matrix(pv_kw=3.5), _rod(), battery=BATTERY)) == [0.0] * SLOTS


def test_a_full_battery_leaves_the_surplus_to_the_rod() -> None:
    assert _rod_kw(_run(_matrix(pv_kw=3.5), _rod(), battery=BATTERY, soc=100.0)) == [ROD_KW] * SLOTS


def test_the_rod_does_not_change_what_the_battery_books() -> None:
    row = _matrix(pv_kw=5.0)[0]
    without, _ = _simulate_single_hour_baseline(
        row, 50.0, BATTERY, flex_kw_override={"rod": 0.0}, consumers=[]
    )
    with_rod, _ = _simulate_single_hour_baseline(
        row, 50.0, BATTERY, flex_kw_override={"rod": ROD_KW}, consumers=[]
    )
    assert with_rod == without


def test_surplus_the_rod_uses_is_no_longer_exported() -> None:
    row = _matrix(pv_kw=5.0)[0]
    _, without = _simulate_single_hour_baseline(
        row, 50.0, NO_BATTERY, flex_kw_override={"rod": 0.0}, consumers=[]
    )
    _, with_rod = _simulate_single_hour_baseline(
        row, 50.0, NO_BATTERY, flex_kw_override={"rod": ROD_KW}, consumers=[]
    )
    assert with_rod["Netzbezug (kW)"] == pytest.approx(without["Netzbezug (kW)"] + ROD_KW)


def test_the_ev_takes_the_surplus_before_the_rod() -> None:
    """Surplus 4.5 kW: the EV draws 3 kW until its 1.5 kWh are in, only then the rod starts."""
    per_slot = _run(_matrix(pv_kw=5.0), _rod(), consumers=[EV], targets={"ev": 1.5})
    assert [slot["ev"] for slot in per_slot] == [3.0, 3.0] + [0.0] * (SLOTS - 2)
    assert _rod_kw(per_slot) == [0.0, 0.0] + [ROD_KW] * (SLOTS - 2)


def test_battery_first_sensitivity_keeps_the_rod_last() -> None:
    params = {**DEFAULT_RULE_PARAMS, "surplus_priority": SURPLUS_BATTERY_FIRST}
    assert _rod_kw(_run(_matrix(pv_kw=3.5), _rod(), battery=BATTERY, params=params)) == [0.0] * SLOTS


def test_ladder_takes_only_rods_beside_a_fuel_source(monkeypatch) -> None:
    rods = [
        {"id": "fuel_rod", "daily_target_source": "heating_rod", "parent_heat_electric": False,
         "nominal_power_kw": ROD_KW},
        {"id": "hp_rod", "daily_target_source": "heating_rod", "parent_heat_electric": True,
         "nominal_power_kw": ROD_KW},
    ]
    balance = RodStoreBalance(capacity_kwh=7.0, start_kwh=2.0, drain_kwh=[0.1] * SLOTS)
    monkeypatch.setattr(
        reference_ladder,
        "_resolve_thermal_flex_contexts",
        lambda matrix, consumers, contexts: {
            c["id"]: {STORE_BALANCE_CONTEXT_KEY: balance} for c in consumers
        },
    )
    monkeypatch.setattr(reference_ladder, "_eligible_slots", lambda setup, consumer, book: book)
    result = reference_ladder._surplus_rods(SimpleNamespace(matrix=_matrix(5.0)), rods, [1, 2])
    assert [rod.cid for rod in result] == ["fuel_rod"]
    assert result[0].nominal_kw == ROD_KW
    assert result[0].eligible == [1, 2]
    assert result[0].balance is balance
    assert result[0].level_kwh == 2.0


def test_the_rods_heat_lowers_the_fuel(monkeypatch) -> None:
    """The ladder's column of the rod is what the fuel balance subtracts."""
    from house_config import heat_source
    from optimizer import thermal_flex_context

    monkeypatch.setattr(heat_source, "heating_rod_part", lambda consumer: {"id": "rod"})
    monkeypatch.setattr(heat_source, "part_kennung", lambda parent, part: f"{parent}_{part}")
    monkeypatch.setattr(heat_source, "consumer_heat_source", lambda consumer: {"type": "gas"})
    monkeypatch.setattr(heat_source, "heat_source_is_electric", lambda source: False)
    monkeypatch.setattr(heat_source, "heat_source_efficiency", lambda source: 0.8)
    monkeypatch.setattr(heat_source, "fuel_price_eur_per_kwh", lambda source: 0.1)
    monkeypatch.setattr(heat_source, "fuel_co2_g_per_kwh", lambda source: 200.0)
    monkeypatch.setattr(
        thermal_flex_context, "thermal_daily_fuel_kwh_for_date", lambda *args, **kwargs: 30.0
    )
    from data import modeled_climate

    monkeypatch.setattr(
        modeled_climate.ModeledClimateContext, "from_scenario", staticmethod(lambda params: None)
    )
    profile = {"consumers": [{"id": "heat", "type": "thermal_annual", "heating_system_id": "x"}]}
    index = pd.date_range(START, periods=96, freq="15min")
    frame = pd.DataFrame({"import_kwh": 0.0, "heat_rod_kw": 0.0}, index=index)
    without = heat_fuel.heat_fuel_for_result(frame, {"_house_profile": profile})
    frame.loc[index[:8], "heat_rod_kw"] = ROD_KW
    with_rod = heat_fuel.heat_fuel_for_result(frame, {"_house_profile": profile})
    assert without["fuel_kwh"] == pytest.approx(30.0)
    assert with_rod["rod_kwh"] == pytest.approx(4.0)
    assert with_rod["fuel_kwh"] == pytest.approx(30.0 - 4.0 / 0.8)
