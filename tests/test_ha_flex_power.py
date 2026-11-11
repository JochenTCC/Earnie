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
        HP_POWER: (2.4, inbox.STATE_OK),
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
    values = {HP_POWER: (0.0 if "0" in state else 2.4, state)}
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
    values = {EV_POWER: (7.0, inbox.STATE_OK)}
    out = hfp.read_ha_flex_chart_kw([EV, second], read_value=_read(values), apply_sign=_no_sign)
    assert out == {}
    assert "share one push signal" in caplog.text


def test_sign_is_applied_with_the_binding_key():
    seen = []

    def flip(value, key):
        seen.append(key)
        return -value

    out = hfp.read_ha_flex_chart_kw(
        [HP], read_value=_read({HP_POWER: (2.0, inbox.STATE_OK)}), apply_sign=flip
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
