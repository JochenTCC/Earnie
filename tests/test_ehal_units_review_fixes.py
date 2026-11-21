"""Units and zero rules of the read paths against the role files (review of 2026-11-21)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ehal.field_registry import apply_loxone_read, loxone_spec
from integrations.ha_carrier_yaml import ehal_base_unit


@pytest.mark.parametrize(
    "ehal_id",
    [
        "consumer.waschmaschine.sens_energy_total",
        "ess.house.sens_ess_energy_charge",
        "ess.house.sens_ess_energy_discharge",
        "sens_pv_energy",
    ],
)
def test_ha_carrier_converts_every_energy_counter_to_kwh(ehal_id: str) -> None:
    # Without a quantity the carrier pushes the entity's number: a Wh meter gives 1000 x.
    assert ehal_base_unit(ehal_id) == "kWh"


@pytest.mark.parametrize(
    "ehal_id",
    [
        "consumer.rod.sens_power_act",
        "heatpump.wp.sens_power_act",
        "pool.spa.sens_power_act",
        "evcs.garage.sens_evcs_active_power",
        "heatpump.wp.sens_heat_power",
    ],
)
def test_ha_carrier_converts_consumer_power_to_w(ehal_id: str) -> None:
    assert ehal_base_unit(ehal_id) == "W"


def test_ha_consumer_power_in_w_is_logged_in_kw() -> None:
    from integrations.ha_flex_power import pushed_power_kw

    assert pushed_power_kw(3000.0, "consumer.rod.sens_power_act") == pytest.approx(3.0)


@pytest.mark.parametrize("kind", ["sens_evcs_active_power", "sens_power_act"])
def test_loxone_consumer_power_unit_comes_from_the_role_file(kind: str) -> None:
    spec = loxone_spec(kind)
    assert spec is not None
    assert (spec.unit, spec.ehal_unit) == ("kW", "W")
    assert apply_loxone_read(7.4, spec) == pytest.approx(7400.0)
    assert apply_loxone_read(-0.2, spec) == pytest.approx(0.0)


def test_loxone_consumer_meter_reads_kw_through_the_role_block() -> None:
    from integrations.loxone_live_power import _read_consumer_meter_kw

    ev = {
        "id": "auto",
        "type": "ev",
        "nominal_power_kw": 11.0,
        "ehal_bindings": {"sens_evcs_active_power": "Earnie_EAuto_Leistung"},
    }
    flex = {
        "id": "trockner",
        "type": "generic",
        "nominal_power_kw": 2.0,
        "ehal_bindings": {"flex.trockner.sens_power_act": "Earnie_Trockner_Leistung"},
    }
    values = {"Earnie_EAuto_Leistung": 7.4, "Earnie_Trockner_Leistung": -0.05}
    with patch(
        "integrations.loxone_live_power.fetch_loxone_generic_value",
        side_effect=lambda name: values.get(name),
    ):
        assert _read_consumer_meter_kw(ev) == pytest.approx(7.4)
        assert _read_consumer_meter_kw(flex) == pytest.approx(0.0)
