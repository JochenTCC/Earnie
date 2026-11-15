"""HeatControl P3: store charge target from the planned energy."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from house_sim.core.heat_pump import HeatPumpStoreParams, HeatPumpStoreState, step_heat_pump_store
from optimizer.heat_storage_target import (
    NO_TARGET_C,
    attach_targets_to_observability,
    operating_mode_deviation,
    store_charge_target_c,
)
from optimizer.thermal_live_store import LiveStorePlan
from optimizer.thermal_model import ThermalBand

TARGET_KEY = "heatpump.waermepumpe.set_temperature_heat_storage_target"


def _plan(*, start=33.0, boost=22.0, store_max=None, draw=2.0, loss=0.0) -> LiveStorePlan:
    return LiveStorePlan(
        forced_hour_flags=[False] * 24,
        floor_electric_kwh=0.0,
        opp_cap_electric_kwh=0.0,
        start_temp_c=start,
        temp_low_c=None,
        used_measured_eq=True,
        used_measured_low=False,
        band=ThermalBand(33.0, 2.0),
        electric_by_hour=[0.0] * 24,
        boost_k=boost,
        store_max_c=store_max,
        capacity_kwh_per_k=1.0,
        heat_loss_kw_per_k=loss,
        jaz=4.0,
        ambient_c=[10.0] * 24,
        draw_kw_by_hour=[draw] * 24,
    )


def test_no_run_now_means_no_target():
    assert store_charge_target_c(_plan(), 0, None) == NO_TARGET_C


def test_target_is_the_planned_level_at_the_end_of_the_run():
    # Band minimum 31 °C, C = 1 kWh/K: a level of 8 kWh is 39 °C.
    assert store_charge_target_c(_plan(), 4, 8.0) == pytest.approx(39.0)


def test_a_run_without_its_level_fails_loud():
    with pytest.raises(ValueError, match="Speicherstand"):
        store_charge_target_c(_plan(), 4, None)


def test_target_stays_inside_setpoint_and_setpoint_plus_boost():
    assert store_charge_target_c(_plan(), 40, 40.0) == pytest.approx(55.0)
    # A run that does not even reach the setpoint still asks for the setpoint.
    assert store_charge_target_c(_plan(), 4, 0.5) == 33.0


def test_reported_maximum_caps_the_target_and_the_charge_band():
    plan = _plan(store_max=50.0)
    assert plan.charge_max_c == 50.0
    assert store_charge_target_c(plan, 40, 40.0) == pytest.approx(50.0)


def test_without_boost_the_target_is_the_setpoint():
    assert store_charge_target_c(_plan(boost=0.0), 8, 2.0) == 33.0


def test_live_headroom_respects_the_reported_maximum():
    from optimizer.thermal_live_store import plan_live_store_horizon

    kwargs = dict(
        start_temp_c=33.0,
        ambient_forecast_c=[5.0] * 24,
        band=ThermalBand(33.0, 2.0),
        capacity_kwh_per_k=1.0,
        heat_loss_kw_per_k=0.0,
        wp_electric_kw=2.0,
        jaz=4.0,
        boost_k=22.0,
    )
    free = plan_live_store_horizon(**kwargs)
    capped = plan_live_store_horizon(**kwargs, store_max_c=45.0)
    assert capped.opp_cap_electric_kwh < free.opp_cap_electric_kwh
    assert capped.charge_max_c == 45.0
    assert len(capped.draw_kw_by_hour) == 24


# --- HouseSim -----------------------------------------------------------------------


def test_house_sim_partial_charge_ends_at_the_target():
    """P3 done criterion: a partial charge ends at the planned target, not at the boost."""
    params = HeatPumpStoreParams(
        capacity_kwh_per_k=1.0, heat_loss_kw_per_k=0.0, heat_power_kw=8.0, cop=4.0,
        setpoint_c=33.0, tolerance_c=2.0, boost_k=22.0, max_c=55.0,
    )
    for inputs in ({"sg_ready_state": 3}, {"enable": 1}, {}):
        state = HeatPumpStoreState(temp_c=30.0)
        for _ in range(16):
            state, _kwh = step_heat_pump_store(
                params, state, demand_kw=0.0, ambient_c=15.0, dt_h=0.25,
                store_target_c=42.0, **inputs,
            )
        assert state.temp_c == pytest.approx(42.0), inputs


def test_house_sim_target_zero_alone_is_normal_operation():
    params = HeatPumpStoreParams(
        capacity_kwh_per_k=1.0, heat_loss_kw_per_k=0.0, heat_power_kw=8.0, cop=4.0,
        setpoint_c=33.0, tolerance_c=2.0, boost_k=22.0,
    )
    state = HeatPumpStoreState(temp_c=30.0)
    for _ in range(16):
        state, _kwh = step_heat_pump_store(
            params, state, demand_kw=0.0, ambient_c=15.0, dt_h=0.25, store_target_c=0.0
        )
    assert state.temp_c == pytest.approx(33.0)


# --- writes ---------------------------------------------------------------------------


def _hp(bindings: dict) -> dict:
    return {"id": "waermepumpe", "name": "WP", "type": "thermal_annual", "ehal_bindings": bindings}


def test_target_is_sent_when_mapped():
    from integrations.loxone_writes import _flexible_consumer_output_values

    values = _flexible_consumer_output_values(
        _hp({TARGET_KEY: ""}), {"waermepumpe": 2.0}, {},
        heat_storage_targets={"waermepumpe": 41.5},
    )
    assert values == {TARGET_KEY: 41.5}


def test_heat_pump_without_target_gets_zero():
    from integrations.loxone_writes import _flexible_consumer_output_values

    values = _flexible_consumer_output_values(
        _hp({TARGET_KEY: ""}), {"waermepumpe": 0.0}, {}, heat_storage_targets={}
    )
    assert values == {TARGET_KEY: 0.0}


def test_no_plan_writes_no_target():
    from integrations.loxone_writes import _flexible_consumer_output_values

    values = _flexible_consumer_output_values(_hp({TARGET_KEY: ""}), {"waermepumpe": 2.0}, {})
    assert values == {}


def test_signal_catalog_offers_the_target_as_optional_write():
    from ehal.signal_catalog import iter_catalog_entries

    house = {"profiles": [{"id": "p", "consumers": [_hp({})]}]}
    entries = [e for e in iter_catalog_entries(house, {}) if e.ehal_id == TARGET_KEY]
    assert [(e.direction, e.is_required, e.binding_key) for e in entries] == [
        ("write", False, TARGET_KEY)
    ]


def test_ha_watchdog_sets_target_zero():
    from ehal.push_signals import Signal
    from integrations.ha_carrier_yaml import _watchdog_automation

    sig = Signal(group="Waermepumpe", ehal_id=TARGET_KEY, old_name="", title="x", digital=False)
    text = "\n".join(_watchdog_automation([sig], None, timeout_s=300))
    assert "ENTITY_heatpump_waermepumpe_set_temperature_heat_storage_target" in text
    assert "value: 0" in text


# --- milp + deviation -----------------------------------------------------------------


def test_targets_from_model_read_the_level_after_the_run():
    from optimizer.heat_storage_target import heat_storage_targets
    from optimizer.thermal_store_model import StoreLevelVars

    powers = [2.0, 2.0, 2.0, 2.0, 0.0, 2.0]
    level_kwh = [2.0, 4.0, 6.0, 8.0, 7.5, 9.5]
    levels = StoreLevelVars(
        levels={slot: SimpleNamespace(varValue=v) for slot, v in enumerate(level_kwh)},
        slack={},
    )
    model = SimpleNamespace(
        horizon=len(powers),
        dt_h=0.25,
        planned_consumers=[{"id": "waermepumpe"}],
        consumer_p={"waermepumpe": [SimpleNamespace(varValue=p) for p in powers]},
        live_store_plans={"waermepumpe": _plan()},
        live_store_levels={"waermepumpe": (None, levels)},
    )
    assert heat_storage_targets(model) == {"waermepumpe": pytest.approx(39.0)}


@pytest.mark.parametrize(
    ("planned", "mode", "expected"),
    [
        (True, 4, "locked"),
        (True, 6, "fault"),
        (True, 1, None),
        (True, 2, None),  # hot water during a planned charge only moves heat
        (False, 1, None),  # the controller's own run
        (True, None, None),
    ],
)
def test_operating_mode_deviation(planned, mode, expected):
    assert operating_mode_deviation(planned, mode) == expected


def test_observability_gets_target_and_deviation():
    items = [
        {"kind": "heat_storage", "consumer_id": "waermepumpe", "feedback": {"sens_operating_mode": 6}},
        {"kind": "thermal_annual", "consumer_id": "x"},
    ]
    attach_targets_to_observability(items, {"waermepumpe": 41.0}, {"waermepumpe": 2.0})
    assert items[0]["heat_control"] == {
        "target_c": 41.0,
        "planned_run": True,
        "operating_mode": 6,
        "deviation": "fault",
        "store_level": None,
    }
    assert "heat_control" not in items[1]
