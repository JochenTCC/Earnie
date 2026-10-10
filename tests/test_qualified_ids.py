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


@pytest.mark.parametrize(
    ("raw", "ns", "kennung", "kind"),
    [
        ("sens_temperature_outside", None, None, "sens_temperature_outside"),
        ("set_grid_export_power_limit", None, None, "set_grid_export_power_limit"),
        ("heartbeat", None, None, "heartbeat"),
        ("grid.meter.sens_grid_power_active", "grid", "meter", "sens_grid_power_active"),
        ("ess.ecoflow_delta_3.sens_ess_soc", "ess", "ecoflow_delta_3", "sens_ess_soc"),
        ("consumer.waschmaschine.set_enable", "consumer", "waschmaschine", "set_enable"),
        ("heatpump.waermepumpe.sens_power_act", "heatpump", "waermepumpe", "sens_power_act"),
        ("pool.pool_filter.set_enable", "pool", "pool_filter", "set_enable"),
        ("evcs.e_auto.set_evcs_max_current", "evcs", "e_auto", "set_evcs_max_current"),
        ("ev.e_auto.get_evcs_ready_by_time", "ev", "e_auto", "get_evcs_ready_by_time"),
        ("inv.wr_main.sens_inv_power_ac", "inv", "wr_main", "sens_inv_power_ac"),
        ("flex.waschmaschine.sens_power_act", "flex", "waschmaschine", "sens_power_act"),
    ],
)
def test_parse_qualified_id(raw: str, ns: str | None, kennung: str | None, kind: str) -> None:
    parsed = q.parse_qualified_id(raw)
    assert parsed is not None
    assert parsed.namespace == ns
    assert parsed.kennung == kennung
    assert parsed.kind == kind
    assert parsed.raw == raw
    assert q.format_qualified_id(parsed) == raw


def test_parse_qualified_id_rejects_junk() -> None:
    assert q.parse_qualified_id("") is None
    assert q.parse_qualified_id("not_a_field") is None
    assert q.parse_qualified_id("foo.bar") is None
    assert q.parse_qualified_id("unknown.slug.sens_x") is None
    assert q.parse_qualified_id("ess..sens_ess_soc") is None
    assert q.parse_qualified_id("ess.BadSlug.sens_ess_soc") is None


@pytest.mark.parametrize(
    ("builder", "args"),
    [
        (q.qualified_plant_id, ("sens_pv_production_active",)),
        (q.qualified_plant_id, ("sens_grid_power_active",)),
        (q.qualified_plant_id, ("set_grid_export_power_limit",)),
        (q.qualified_grid_id, ("sens_grid_energy_import",)),
        (q.qualified_battery_id, ("15_kwh_speicher", "sens_ess_soc")),
        (q.qualified_consumer_id, ("waschmaschine", "generic", "set_enable")),
        (q.qualified_consumer_id, ("e_auto", "ev", "set_evcs_max_current")),
        (q.qualified_consumer_id, ("e_auto", "ev", "sens_evcs_soc_act")),
        (q.qualified_consumer_id, ("waermepumpe", "thermal_annual", "sens_power_act")),
        (q.qualified_consumer_id, ("pool_swimspa", "thermal_rc", "set_enable")),
    ],
)
def test_builder_parse_round_trip(builder, args) -> None:
    built = builder(*args)
    parsed = q.parse_qualified_id(built)
    assert parsed is not None
    assert q.format_qualified_id(parsed) == built
    if parsed.namespace is None:
        assert built == parsed.kind
    else:
        assert built == f"{parsed.namespace}.{parsed.kennung}.{parsed.kind}"
