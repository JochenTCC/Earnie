"""HeatControl P2: fixed boost, SG-Ready state write and HA watchdog."""
from __future__ import annotations

import pytest

from ehal.heat_fields import (
    KIND_SET_SG_READY_STATE,
    SG_READY_CHARGE,
    SG_READY_NORMAL,
    sg_ready_state_for_plan,
)
from optimizer.hp_store import hp_store_capacity
from optimizer.thermal_coupled import normalize_heat_storage
from optimizer.thermal_live_store import plan_live_store_horizon
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume

STATE_KEY = "heatpump.waermepumpe.set_sg_ready_state"
ENABLE_KEY = "heatpump.waermepumpe.set_enable"


def _hp(bindings: dict) -> dict:
    return {
        "id": "waermepumpe",
        "name": "Wärmepumpe",
        "type": "thermal_annual",
        "ehal_bindings": bindings,
    }


# --- boost ---------------------------------------------------------------------------


def test_boost_defaults_to_zero_and_rejects_negative():
    assert normalize_heat_storage({"volume_liters": 900})["boost_k"] == 0.0
    assert normalize_heat_storage({"volume_liters": 900, "boost_k": 22})["boost_k"] == 22.0
    with pytest.raises(ValueError, match="boost_k"):
        normalize_heat_storage({"volume_liters": 900, "boost_k": -1})


def _plan(boost_k: float):
    return plan_live_store_horizon(
        start_temp_c=33.0,
        ambient_forecast_c=[5.0] * 24,
        band=ThermalBand(33.0, 2.0),
        capacity_kwh_per_k=1.0,
        heat_loss_kw_per_k=0.005,
        wp_electric_kw=2.0,
        jaz=4.0,
        boost_k=boost_k,
    )


def test_live_opportunistic_headroom_reaches_setpoint_plus_boost():
    """Backend band 31–35 °C, boost 22 K: Earnie may charge to 55 °C, not only 33 °C."""
    without = _plan(0.0)
    with_boost = _plan(22.0)
    assert without.opp_cap_electric_kwh == pytest.approx(0.0)
    assert with_boost.opp_cap_electric_kwh > 0.0
    assert with_boost.charge_max_c == pytest.approx(55.0)
    # Normal operation (forced hours) does not depend on the boost.
    assert with_boost.forced_hour_flags == without.forced_hour_flags


def test_scenario_explorer_store_band_includes_boost():
    store = {"volume_liters": 900, "setpoint_c": 33, "tolerance_c": 2}
    capacity = capacity_kwh_per_k_from_volume(900)
    base = hp_store_capacity({"thermal": {"heat_storage": store}})
    boosted = hp_store_capacity({"thermal": {"heat_storage": {**store, "boost_k": 22}}})
    assert base.store_kwh == pytest.approx(capacity * 2)
    assert boosted.store_kwh == pytest.approx(capacity * 24)


# --- state -----------------------------------------------------------------------------


def test_state_follows_the_plan():
    assert sg_ready_state_for_plan(True) == SG_READY_CHARGE == 3
    assert sg_ready_state_for_plan(False) == SG_READY_NORMAL == 2


@pytest.mark.parametrize(("power_kw", "state", "enable"), [(2.0, 3.0, 1.0), (0.0, 2.0, 0.0)])
def test_state_sent_next_to_enable(power_kw, state, enable):
    from integrations.loxone_writes import _flexible_consumer_output_values

    consumer = _hp({ENABLE_KEY: "", STATE_KEY: ""})
    values = _flexible_consumer_output_values(consumer, {"waermepumpe": power_kw}, {})
    assert values == {ENABLE_KEY: enable, STATE_KEY: state}


def test_state_alone_is_sent_without_enable():
    from integrations.loxone_writes import _flexible_consumer_output_values

    values = _flexible_consumer_output_values(
        _hp({STATE_KEY: "Earnie_Waermepumpe_SG_Ready_Soll"}), {"waermepumpe": 1.5}, {}
    )
    assert values == {"Earnie_Waermepumpe_SG_Ready_Soll": 3.0}


def test_no_state_without_binding():
    from integrations.loxone_writes import _flexible_consumer_output_values

    values = _flexible_consumer_output_values(_hp({ENABLE_KEY: ""}), {"waermepumpe": 1.5}, {})
    assert values == {ENABLE_KEY: 1.0}


def test_state_publishes_its_qualified_id(monkeypatch):
    from integrations import loxone_writes

    published: list[tuple[str, float]] = []
    monkeypatch.setattr(
        loxone_writes,
        "_publish_setpoint_traced",
        lambda qid, value, io_name: published.append((qid, value)) or (qid, value),
    )
    consumer = _hp({ENABLE_KEY: "", STATE_KEY: "Earnie_Waermepumpe_SG_Ready_Soll"})
    loxone_writes._publish_flexible_consumer_outputs(
        consumer,
        {ENABLE_KEY: 0.0, "Earnie_Waermepumpe_SG_Ready_Soll": 2.0},
        kinds=frozenset({"set_enable", KIND_SET_SG_READY_STATE}),
    )
    assert sorted(published) == [(ENABLE_KEY, 0.0), (STATE_KEY, 2.0)]


def test_signal_catalog_offers_the_state_as_optional_write():
    from ehal.signal_catalog import iter_catalog_entries

    house = {"profiles": [{"id": "p", "consumers": [_hp({ENABLE_KEY: ""})]}]}
    entries = [
        e for e in iter_catalog_entries(house, {}) if e.ehal_id == STATE_KEY
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.direction == "write"
    assert not entry.is_required
    assert not entry.is_activated
    assert entry.binding_key == STATE_KEY


# --- HA watchdog -----------------------------------------------------------------------


def test_ha_watchdog_sets_state_2_when_earnie_is_unreachable():
    from ehal.push_signals import Signal
    from integrations.ha_carrier_yaml import _watchdog_automation

    sig = Signal(group="Waermepumpe", ehal_id=STATE_KEY, old_name="", title="x", digital=False)
    lines = _watchdog_automation([sig], None, timeout_s=300)
    text = "\n".join(lines)
    assert "ENTITY_heatpump_waermepumpe_set_sg_ready_state" in text
    assert "value: 2" in text
    assert _watchdog_automation([sig], None, timeout_s=0) == []
