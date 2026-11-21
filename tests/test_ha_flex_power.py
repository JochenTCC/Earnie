"""Ledger P9e: per-consumer power from the HA push inbox into the power sampler's flex_kw."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ehal.push_signals import pilot_id
from integrations import ha_flex_power as hfp
from runtime_store import ehal_push_inbox as inbox
from runtime_store import power_interval_sampler as sampler

HP = {
    "id": "wp",
    "type": "thermal_annual",
    "nominal_power_kw": 3.0,
    "signal_type": "binary",
    "ehal_bindings": {"flex.wp.sens_power_act": "sensor.wp_power", "flex.wp.sens_consumer_active": "binary_sensor.wp"},
}
DRYER = {
    "id": "trockner",
    "type": "generic",
    "nominal_power_kw": 2.0,
    "signal_type": "binary",
    "ehal_bindings": {"flex.trockner.sens_consumer_active": "binary_sensor.trockner"},
}
EV = {
    "id": "auto",
    "type": "ev",
    "nominal_power_kw": 11.0,
    "signal_type": "power",
    "min_power_kw": 1.4,
    "ehal_bindings": {"evcs.wb1.sens_evcs_active_power": "sensor.wb1_power"},
}
UNBOUND = {"id": "pool", "type": "generic", "nominal_power_kw": 0.2, "signal_type": "binary"}
# A modulating consumer with only a run state: on/off says nothing about its power.
MODULATING = {
    "id": "heizstab",
    "type": "generic",
    "nominal_power_kw": 3.0,
    "signal_type": "power",
    "min_power_kw": 0.5,
    "ehal_bindings": {"flex.heizstab.sens_consumer_active": "binary_sensor.rod", "set_evcs_max_current": ""},
}


def _qid(consumer: dict, key: str) -> str:
    return pilot_id("consumer", consumer["id"], key, consumer["type"])


HP_POWER = _qid(HP, "flex.wp.sens_power_act")
DRYER_ACTIVE = _qid(DRYER, "flex.trockner.sens_consumer_active")
EV_POWER = "evcs.wb1.sens_evcs_active_power"


def _read(values: dict[str, tuple[float | None, str]]):
    def read_value(qid: str):
        return values.get(qid, (None, inbox.STATE_READ_ERROR))

    return read_value


def _no_sign(value: float, _key: str) -> float:
    return value


def test_ev_qid_keeps_its_wallbox():
    assert _qid(EV, "evcs.wb1.sens_evcs_active_power") == EV_POWER


def test_measured_values_give_kw_per_consumer():
    values = {
        HP_POWER: (2400.0, inbox.STATE_OK),
        DRYER_ACTIVE: (1.0, inbox.STATE_DIGITAL_HELD),
        EV_POWER: (0.0, inbox.STATE_ZERO_HELD),
    }
    out = hfp.read_ha_flex_chart_kw([HP, DRYER, EV, UNBOUND], read_value=_read(values), apply_sign=_no_sign)
    # the heat pump has a power entity: that wins over its run state
    assert out == {"wp": 2.4, "trockner": 2.0, "auto": 0.0}


@pytest.mark.parametrize(
    "state",
    [
        inbox.STATE_ZERO_ASSUMED_SILENT,
        inbox.STATE_ZERO_ASSUMED_NEVER,
        inbox.STATE_LAST_KNOWN,
        inbox.STATE_ZERO_HELD_NO_LINK,
        inbox.STATE_READ_ERROR,
    ],
)
def test_stale_or_assumed_power_gives_no_key_never_zero(state):
    values = {HP_POWER: (0.0 if "0" in state else 2400.0, state)}
    out = hfp.read_ha_flex_chart_kw([HP], read_value=_read(values), apply_sign=_no_sign)
    assert out == {}


def test_missing_value_and_unbound_consumer_give_no_key():
    out = hfp.read_ha_flex_chart_kw([HP, UNBOUND], read_value=_read({}), apply_sign=_no_sign)
    assert out == {}


def test_run_state_counts_only_for_on_off_consumers():
    values = {_qid(MODULATING, "flex.heizstab.sens_consumer_active"): (1.0, inbox.STATE_OK)}
    out = hfp.read_ha_flex_chart_kw([MODULATING], read_value=_read(values), apply_sign=_no_sign)
    assert out == {}


def test_two_evs_on_one_wallbox_get_no_key(caplog):
    second = EV | {"id": "auto2"}
    values = {EV_POWER: (7000.0, inbox.STATE_OK)}
    out = hfp.read_ha_flex_chart_kw([EV, second], read_value=_read(values), apply_sign=_no_sign)
    assert out == {}
    assert "share one push signal" in caplog.text


def test_wallbox_power_is_pushed_in_w_and_logged_in_kw():
    """The carrier pushes ``sens_evcs_active_power`` in its EHAL unit W; flex_kw is kW."""
    from integrations.ha_carrier_yaml import ehal_base_unit

    assert ehal_base_unit(EV_POWER) == "W"
    values = {EV_POWER: (7400.0, inbox.STATE_OK), HP_POWER: (2400.0, inbox.STATE_OK)}
    out = hfp.read_ha_flex_chart_kw([EV, HP], read_value=_read(values), apply_sign=_no_sign)
    # sens_power_act is a power too: the carrier pushes W whatever unit the entity has
    assert out == {"auto": 7.4, "wp": 2.4}


def test_sign_is_applied_with_the_binding_key():
    seen = []

    def flip(value, key):
        seen.append(key)
        return -value

    out = hfp.read_ha_flex_chart_kw(
        [HP], read_value=_read({HP_POWER: (2000.0, inbox.STATE_OK)}), apply_sign=flip
    )
    assert out == {"wp": -2.0}
    assert seen == ["flex.wp.sens_power_act"]


# --- sampler: slot mean in closed_interval.flex_kw ------------------------------------


def test_ha_backend_samples_consumer_power_into_the_slot_mean(tmp_path, monkeypatch):
    from integrations import ehal_live

    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "is_ehal_network_backend", lambda: True)
    readings = iter([{"wp": 2.0}, {"wp": 3.0}, {"wp": 1.0}, {}])
    monkeypatch.setattr(hfp, "read_ha_flex_chart_kw_live", lambda: next(readings))

    state = tmp_path / "sampler.json"
    start = datetime(2026, 11, 1, 13, 0)
    plant = {"pv": 1.0, "house": 4.0, "grid": 3.0, "battery": 0.0}
    for k in range(4):
        assert sampler.tick(
            now=start + timedelta(seconds=30 * (k + 1)),
            force=True,
            state_path=str(state),
            read_plant=lambda: plant,
            read_soc=lambda: 50.0,
        )
    closed = sampler.finalize_closed_interval(start, state_path=str(state))
    # the fourth sample had no reading (stale): it counts as 0 in the mean, as on Loxone
    assert closed["flex_kw"] == {"wp": pytest.approx(1.5)}


def test_openems_logs_no_consumer_power(tmp_path, monkeypatch):
    from integrations import ehal_live

    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: False)
    monkeypatch.setattr(ehal_live, "is_ehal_network_backend", lambda: True)
    monkeypatch.setattr(hfp, "read_ha_flex_chart_kw_live", lambda: pytest.fail("HA reader on OpenEMS"))
    state = tmp_path / "sampler.json"
    start = datetime(2026, 11, 1, 13, 0)
    assert sampler.tick(
        now=start + timedelta(seconds=30),
        force=True,
        state_path=str(state),
        read_plant=lambda: {"pv": 1.0, "house": 4.0, "grid": 3.0, "battery": 0.0},
        read_soc=lambda: 50.0,
    )
    assert sampler.finalize_closed_interval(start, state_path=str(state))["flex_kw"] == {}


# --- heating rod: planning snapshot and cons_data on HA (HA Lab 2026-11-17) ------------

ROD_ID = "wp_heating_rod"
ROD_POWER = f"heatpump.{ROD_ID}.sens_power_act"
ROD_ACTIVE = f"heatpump.{ROD_ID}.sens_consumer_active"
ROD = {
    "id": ROD_ID,
    "type": "heating_rod",
    "parent_id": "wp",
    "nominal_power_kw": 3.0,
    "signal_type": "binary",
    "daily_target_source": "heating_rod",
    "ehal_bindings": {f"heatpump.{ROD_ID}.set_enable": "", ROD_POWER: "", ROD_ACTIVE: ""},
}


def test_rod_qids_are_its_qualified_bindings():
    assert _qid(ROD, ROD_POWER) == ROD_POWER
    assert _qid(ROD, ROD_ACTIVE) == ROD_ACTIVE


def test_rod_power_is_read_and_other_consumers_are_left_out():
    values = {ROD_POWER: (3000.0, inbox.STATE_OK), HP_POWER: (2400.0, inbox.STATE_OK)}
    out = hfp.read_ha_heating_rod_kw([HP, ROD], read_value=_read(values), apply_sign=_no_sign)
    assert out == {ROD_ID: 3.0}


def test_rod_without_a_meter_counts_run_state_times_nominal_power():
    rod = ROD | {"ehal_bindings": {f"heatpump.{ROD_ID}.set_enable": "", ROD_ACTIVE: ""}}
    on = hfp.read_ha_heating_rod_kw(
        [rod], read_value=_read({ROD_ACTIVE: (1.0, inbox.STATE_OK)}), apply_sign=_no_sign
    )
    off = hfp.read_ha_heating_rod_kw(
        [rod], read_value=_read({ROD_ACTIVE: (0.0, inbox.STATE_ZERO_HELD)}), apply_sign=_no_sign
    )
    assert on == {ROD_ID: 3.0}
    assert off == {ROD_ID: 0.0}


def test_unmeasured_rod_gets_no_key_and_a_warning(caplog):
    out = hfp.read_ha_heating_rod_kw([ROD], read_value=_read({}), apply_sign=_no_sign)
    assert out == {}
    assert f"Heizstab '{ROD_ID}'" in caplog.text


def test_network_flex_live_kw_reads_rods_on_ha_only(monkeypatch):
    from integrations import ehal_live, ehal_live_ops

    monkeypatch.setattr(hfp, "read_ha_heating_rod_kw_live", lambda consumers: {ROD_ID: 3.0})
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    assert ehal_live_ops.fetch_network_flex_live_kw([ROD]) == {ROD_ID: 3.0}
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: False)
    assert ehal_live_ops.fetch_network_flex_live_kw([ROD]) == {}
