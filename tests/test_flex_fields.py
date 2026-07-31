"""Pattern B flex EHAL field helpers."""
from __future__ import annotations

from ehal.flex_fields import (
    expand_flex_bindings,
    flex_ehal_slug,
    flex_sens_power_act,
    flex_set_enable,
    is_flex_sens_power_act_field,
)


def test_zaehler_slug_strips_prefix():
    assert flex_ehal_slug("zaehler_trockner") == "trockner"
    assert flex_sens_power_act("zaehler_trockner") == "flex.trockner.sens_power_act"
    assert flex_set_enable("waschmaschine") == "flex.waschmaschine.set_enable"


def test_expand_legacy_stubs():
    out = expand_flex_bindings(
        {
            "flex.power_name": "Zähler Trockner",
            "flex.enable_name": "En",
            "sens_evcs_connected": "Da",
        },
        "zaehler_trockner",
    )
    assert out == {
        "flex.trockner.sens_power_act": "Zähler Trockner",
        "flex.trockner.set_enable": "En",
        "sens_evcs_connected": "Da",
    }
    assert is_flex_sens_power_act_field("flex.power_name")
    assert is_flex_sens_power_act_field("flex.trockner.sens_power_act")
