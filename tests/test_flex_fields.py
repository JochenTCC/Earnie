"""Entity-scoped / typed consumer EHAL field helpers."""
from __future__ import annotations

from ehal.flex_fields import (
    binding_address,
    canonicalize_consumer_bindings,
    consumer_fields_for_consumer,
    consumer_storage_field,
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


def test_canonicalize_legacy_stubs_to_typed():
    out = canonicalize_consumer_bindings(
        {
            "flex.power_name": "Zähler Trockner",
            "flex.enable_name": "En",
            "sens_evcs_connected": "Da",
        },
        "zaehler_trockner",
        "generic",
    )
    assert out == {
        "consumer.trockner.sens_power_act": "Zähler Trockner",
        "consumer.trockner.set_enable": "En",
        "sens_evcs_connected": "Da",
    }
    assert is_flex_sens_power_act_field("flex.power_name")
    assert is_flex_sens_power_act_field("flex.trockner.sens_power_act")
    assert is_flex_sens_power_act_field("consumer.trockner.sens_power_act")


def test_canonicalize_heatpump_and_pool_namespaces():
    assert consumer_storage_field("wp", "thermal_annual", "set_enable") == (
        "heatpump.wp.set_enable"
    )
    assert consumer_storage_field("pool_filter", "thermal_rc", "sens_power_act") == (
        "pool.pool_filter.sens_power_act"
    )
    assert consumer_fields_for_consumer("wm", "generic")[0] == (
        "consumer.wm.sens_power_act"
    )


def test_expand_flex_bindings_delegates_to_canonicalize():
    out = expand_flex_bindings(
        {"flex.waschmaschine.sens_power_act": "P"},
        "waschmaschine",
        "generic",
    )
    assert out == {"consumer.waschmaschine.sens_power_act": "P"}


def test_binding_address_prefers_typed_then_legacy():
    bindings = {
        "consumer.wm.sens_power_act": "Typed",
        "flex.wm.sens_power_act": "Legacy",
    }
    assert binding_address(bindings, "wm", "sens_power_act", consumer_type="generic") == (
        "Typed"
    )
    assert binding_address(
        {"flex.wm.sens_power_act": "Legacy"}, "wm", "sens_power_act"
    ) == "Legacy"
