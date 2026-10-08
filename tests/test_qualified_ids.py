"""Qualified EHAL IDs: <namespace>.<Kennung>.<field> (2.7.n-2 pilot start)."""
from __future__ import annotations

import pytest

from ehal import qualified_ids as q
from runtime_store.loxone_push_inbox import is_valid_ehal_id


@pytest.mark.parametrize(
    ("consumer_id", "ctype", "key", "expected"),
    [
        # generic consumers → consumer, stored legacy flex.* key or bare
        ("waschmaschine", "generic", "flex.waschmaschine.sens_power_act", "consumer.waschmaschine.sens_power_act"),
        ("waschmaschine", "generic", "flex.waschmaschine.set_enable", "consumer.waschmaschine.set_enable"),
        ("zaehler_trockner", "generic", "flex.trockner.sens_power_act", "consumer.trockner.sens_power_act"),
        # heat pump
        ("waermepumpe", "thermal_annual", "flex.waermepumpe.sens_power_act", "heatpump.waermepumpe.sens_power_act"),
        (
            "waermepumpe",
            "thermal_annual",
            "sens_temperature_heat_storage",
            "heatpump.waermepumpe.sens_temperature_heat_storage",
        ),
        # pool incl. the filter entity (generic type, by id)
        ("pool_swimspa", "thermal_rc", "sens_temperature_water", "pool.pool_swimspa.sens_temperature_water"),
        ("pool_filter", "generic", "get_filter_remaining_hours", "pool.pool_filter.get_filter_remaining_hours"),
        # EV: wallbox vs vehicle by field kind
        ("e_auto", "ev", "sens_evcs_active_power", "evcs.e_auto.sens_evcs_active_power"),
        ("e_auto", "ev", "sens_evcs_connected", "evcs.e_auto.sens_evcs_connected"),
        ("e_auto", "ev", "sens_evcs_soc_act", "ev.e_auto.sens_evcs_soc_act"),
        ("e_auto", "ev", "get_evcs_limit_soc", "ev.e_auto.get_evcs_limit_soc"),
    ],
)
def test_qualified_consumer_id(consumer_id: str, ctype: str, key: str, expected: str) -> None:
    assert q.qualified_consumer_id(consumer_id, ctype, key) == expected


def test_qualified_battery_id() -> None:
    assert q.qualified_battery_id("ecoflow_delta_3", "ess.ecoflow_delta_3.sens_ess_soc") == (
        "ess.ecoflow_delta_3.sens_ess_soc"
    )
    assert q.qualified_battery_id("15_kwh_speicher", "sens_ess_soc") == "ess.15_kwh_speicher.sens_ess_soc"


def test_every_read_result_is_accepted_by_the_inbox() -> None:
    for consumer_id, ctype, key in [
        ("waschmaschine", "generic", "flex.waschmaschine.sens_power_act"),
        ("waermepumpe", "thermal_annual", "sens_temperature_heat_storage_low"),
        ("pool_swimspa", "thermal_rc", "get_temperature_tolerance_c"),
        ("pool_filter", "generic", "sens_filter_active"),
        ("e_auto", "ev", "sens_evcs_bat_capacity"),
    ]:
        assert is_valid_ehal_id(q.qualified_consumer_id(consumer_id, ctype, key))


def test_flex_is_legacy_only() -> None:
    assert "flex" not in q.NAMESPACES
    assert "flex" in q.LEGACY_NAMESPACES
    assert "flex" not in q.id_namespace_alternation(include_legacy=False).split("|")
    assert "flex" in q.id_namespace_alternation().split("|")
    assert is_valid_ehal_id("flex.waschmaschine.sens_power_act")  # still accepted on input


def test_digital_ids() -> None:
    assert q.is_digital_id("sens_absent_mode")
    assert q.is_digital_id("evcs.e_auto.sens_evcs_connected")
    assert q.is_digital_id("pool.pool_filter.sens_filter_active")
    assert q.is_digital_id("consumer.waschmaschine.sens_consumer_active")
    assert not q.is_digital_id("evcs.e_auto.sens_evcs_active_power")
    assert not q.is_digital_id("heartbeat")
