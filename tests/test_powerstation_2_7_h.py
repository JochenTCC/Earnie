"""2.7.h — physical standby_backup, source_select, rolling MILP."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ehal import EHAL_SCHEMA_VERSION, validate_capabilities, validate_setpoint
from ehal.ess_fields import ESS_FIELD_KINDS, ess_field
from ehal.functions import available_functions
from house_config.powerstation import ROLE_STANDBY_BACKUP
from integrations.ha_adapter import (
    BOOLEAN_INVERT_FIELDS,
    HaAdapter,
    HaConfig,
    apply_boolean_invert,
)
from optimizer.powerstation_standby import (
    SOURCE_BATTERY,
    SOURCE_GRID,
    apply_standby_load_relief,
    attached_load_kw,
    collect_standby_packs,
    live_source_and_charge,
    plan_standby_horizon,
    reserve_target_kwh_for_standby,
)


def test_schema_version_is_4():
    assert EHAL_SCHEMA_VERSION == 4


def test_set_ess_source_select_in_ess_kinds():
    assert "set_ess_source_select" in ESS_FIELD_KINDS
    assert ess_field("delta3", "set_ess_source_select") == (
        "ess.delta3.set_ess_source_select"
    )


def test_validate_setpoint_source_select():
    doc = validate_setpoint(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-10-06T00:00:00Z",
            "adapter_id": "test",
            "set_ess_source_select": 1,
        }
    )
    assert doc["set_ess_source_select"] == 1


def test_validate_capabilities_source_select_optional():
    doc = validate_capabilities(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-10-06T00:00:00Z",
            "adapter_id": "test",
            "supports_ess_write": True,
            "supports_evcs_current": False,
            "supports_ess_source_select": True,
        }
    )
    assert doc["supports_ess_source_select"] is True


def test_ess_source_select_function_from_pattern_b():
    funcs = available_functions(
        {"ess.delta3.set_ess_source_select": "switch.delta_3_grid_bypass"}
    )
    assert "ess_source_select" in funcs


def test_boolean_invert_identity_and_flip():
    assert apply_boolean_invert(1, "ehal") == 1.0
    assert apply_boolean_invert(0, "ehal") == 0.0
    assert apply_boolean_invert(1, "invert") == 0.0
    assert apply_boolean_invert(0, "invert") == 1.0
    assert "set_ess_source_select" in BOOLEAN_INVERT_FIELDS


def test_collect_skips_virtual_standby():
    packs = collect_standby_packs(
        powerstations=[
            {
                "id": "virt",
                "type": "powerstation",
                "backing": "virtual",
                "role": ROLE_STANDBY_BACKUP,
                "attached_consumer_ids": ["nas"],
                "battery_capacity_kwh": 2.0,
            },
            {
                "id": "delta3",
                "type": "powerstation",
                "backing": "physical",
                "role": ROLE_STANDBY_BACKUP,
                "attached_consumer_ids": ["nas"],
                "battery_capacity_kwh": 1.0,
                "battery_max_charge_power_kw": 1.0,
            },
        ],
        appliances=[{"id": "nas", "default_power_kw": 0.15}],
    )
    assert len(packs) == 1
    assert packs[0]["powerstation_id"] == "delta3"
    assert packs[0]["load_kw"] == pytest.approx(0.15)


def test_attached_load_and_reserve_sizing():
    load = attached_load_kw(
        {"attached_consumer_ids": ["a", "b"]},
        {"a": {"default_power_kw": 0.1}, "b": {"default_power_kw": 0.05}},
    )
    assert load == pytest.approx(0.15)
    assert reserve_target_kwh_for_standby(
        load_kw=0.15, expensive_hours=4.0, capacity_kwh=1.0
    ) == pytest.approx(0.6)


def test_plan_standby_islands_expensive_slots():
    # Cheap then expensive: expect charge in cheap, island in expensive when SoC allows.
    matrix = [
        {"k_act": 0.05, "expected_p_act": 1.0, "expected_p_pv": 0.0},
        {"k_act": 0.40, "expected_p_act": 1.0, "expected_p_pv": 0.0},
        {"k_act": 0.40, "expected_p_act": 1.0, "expected_p_pv": 0.0},
        {"k_act": 0.05, "expected_p_act": 1.0, "expected_p_pv": 0.0},
    ]
    packs = [
        {
            "powerstation_id": "delta3",
            "load_kw": 0.2,
            "capacity_kwh": 1.0,
            "max_charge_power_kw": 1.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "efficiency": 0.95,
        }
    ]
    plans = plan_standby_horizon(
        matrix, packs, current_soc_by_id={"delta3": 80.0}, dt_h=0.25
    )
    assert "delta3" in plans
    selects = plans["delta3"]["source_select"]
    assert len(selects) == 4
    # At least one expensive slot should island when starting at 80% SoC.
    assert SOURCE_BATTERY in selects
    sources, charges = live_source_and_charge(plans, slot=0)
    assert sources["delta3"] in (SOURCE_GRID, SOURCE_BATTERY)
    if sources["delta3"] == SOURCE_BATTERY:
        assert charges["delta3"] == 0.0


def test_apply_standby_load_relief():
    matrix = [
        {"expected_p_act": 1.0, "k_act": 0.2},
        {"expected_p_act": 1.0, "k_act": 0.2},
    ]
    plans = {
        "delta3": {
            "source_select": [SOURCE_BATTERY, SOURCE_GRID],
            "load_kw": 0.2,
        }
    }
    out = apply_standby_load_relief(matrix, plans)
    assert out[0]["expected_p_act"] == pytest.approx(0.8)
    assert out[1]["expected_p_act"] == pytest.approx(1.0)
    assert matrix[0]["expected_p_act"] == pytest.approx(1.0)  # original untouched


def test_ha_switch_write_source_select():
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha.local",
            token="t",
            adapter_id="test",
            entities={"set_ess_source_select": "switch.delta_3_grid_bypass"},
        )
    )
    calls: list[tuple] = []

    def fake_service(domain, service, data):
        calls.append((domain, service, data))

    adapter.call_service = fake_service  # type: ignore[method-assign]
    error = adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-10-06T00:00:00Z",
            "adapter_id": "test",
            "set_ess_source_select": 1,
        }
    )
    assert error is None
    assert calls == [
        ("switch", "turn_on", {"entity_id": "switch.delta_3_grid_bypass"})
    ]

    calls.clear()
    adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-10-06T00:00:00Z",
            "adapter_id": "test",
            "set_ess_source_select": 0,
        }
    )
    assert calls == [
        ("switch", "turn_off", {"entity_id": "switch.delta_3_grid_bypass"})
    ]


def test_ha_switch_write_with_invert():
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha.local",
            token="t",
            adapter_id="test",
            entities={"set_ess_source_select": "switch.odd"},
            boolean_invert={"set_ess_source_select": "invert"},
        )
    )
    calls: list[tuple] = []
    adapter.call_service = lambda d, s, data: calls.append((d, s, data))  # type: ignore
    adapter.write_setpoints(
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-10-06T00:00:00Z",
            "adapter_id": "test",
            "set_ess_source_select": 1,
        }
    )
    assert calls[0][1] == "turn_off"


def test_write_standby_source_selects_loxone_marker():
    from optimizer import powerstation_live as psl

    psl._last_powerstation_sent.clear()
    with patch.object(psl, "_planning_powerstations", return_value=[]), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=False
    ), patch(
        "integrations.ehal_live.is_ehal_network_backend", return_value=False
    ), patch(
        "house_config.ehal_bindings.resolve_plant_binding",
        return_value="Earnie_Speicher_Quellenwahl",
    ), patch(
        "optimizer.live_export_limit.load_house_doc", return_value={}
    ), patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as send:
        send.return_value = MagicMock(success=True)
        psl.write_standby_source_selects({"delta3": 1})
        send.assert_called()
        assert psl.last_powerstation_sent().get("set_ess_source_select") == 1.0


def test_ha_charge_does_not_remap_to_house_battery():
    """Unmapped PS charge/discharge must not write plant-flat house entities."""
    from optimizer import powerstation_live as psl

    adapter = MagicMock()
    adapter.cfg.entities = {
        "set_ess_charge_power_limit": "number.house_charge",
        "set_ess_discharge_power_limit": "number.house_discharge",
    }
    adapter.cfg.adapter_id = "ha-test"
    adapter.write_mapped_fields = MagicMock(return_value=None)
    persisted: list = []

    with patch.object(psl, "_planning_powerstations", return_value=[]), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "runtime_store.shadow.writes.should_invoke_setpoint_writes", return_value=True
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=True
    ), patch(
        "integrations.ehal_live.get_ha_adapter", return_value=adapter
    ), patch(
        "integrations.ehal_live.persist_write_error", side_effect=persisted.append
    ):
        psl.write_physical_powerstation_charges({"delta3": 1.0})

    adapter.write_mapped_fields.assert_not_called()
    assert len(persisted) == 1
    assert persisted[0]["failed_fields"] == ["set_ess_charge_power_limit"]
    assert "ess.delta3.set_ess_charge_power_limit" in persisted[0]["message"]


def test_loxone_charge_does_not_use_plant_merker():
    """Unmapped PS charge must not send the house battery plant Merker."""
    from optimizer import powerstation_live as psl

    psl._last_powerstation_sent.clear()
    persisted: list = []

    def plant_binding(_house, kind, *_a, **_k):
        if kind == "set_ess_charge_power_limit":
            return "Earnie_LadeLeistungs-Limit"
        if kind == "set_ess_discharge_power_limit":
            return "Earnie_EntladeLeistungs-Limit"
        return ""

    with patch.object(psl, "_planning_powerstations", return_value=[]), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "runtime_store.shadow.writes.should_invoke_setpoint_writes", return_value=True
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=False
    ), patch(
        "integrations.ehal_live.is_ehal_network_backend", return_value=False
    ), patch(
        "house_config.ehal_bindings.resolve_plant_binding", side_effect=plant_binding
    ), patch(
        "optimizer.live_export_limit.load_house_doc", return_value={}
    ), patch(
        "integrations.ehal_live.persist_write_error", side_effect=persisted.append
    ), patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as send:
        send.return_value = MagicMock(success=True)
        psl.write_physical_powerstation_charges({"delta3": 1.0})

    send.assert_not_called()
    assert len(persisted) == 1
    assert persisted[0]["failed_fields"] == ["set_ess_charge_power_limit"]
    assert "ess.delta3.set_ess_charge_power_limit" in persisted[0]["message"]


def test_loxone_charge_only_when_discharge_unmapped():
    """EcoFlow-style: charge Merker present, no discharge → write charge, no Schreibfehler."""
    from ehal.ess_fields import ess_field
    from optimizer import powerstation_live as psl

    psl._last_powerstation_sent.clear()
    persisted: list = []
    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "ehal_bindings": {
                ess_field(slug, "set_ess_charge_power_limit"): "PS_Charge_Limit",
            },
        }
    ]

    with patch.object(psl, "_planning_powerstations", return_value=planning), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "runtime_store.shadow.writes.should_invoke_setpoint_writes", return_value=True
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=False
    ), patch(
        "integrations.ehal_live.is_ehal_network_backend", return_value=False
    ), patch(
        "integrations.ehal_live.persist_write_error", side_effect=persisted.append
    ), patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as send:
        send.return_value = MagicMock(success=True)
        psl.write_physical_powerstation_charges({slug: 1.5})

    send.assert_called_once()
    assert send.call_args[0][0] == ess_field(slug, "set_ess_charge_power_limit")
    assert send.call_args[0][1] == pytest.approx(1.5)
    assert send.call_args.kwargs.get("io_name") == "PS_Charge_Limit"
    assert persisted == []
    sent = psl.last_powerstation_sent()
    # Pattern-B key per powerstation; the flat key belongs to the house battery.
    assert sent.get(ess_field(slug, "set_ess_charge_power_limit")) == 1.5
    assert "set_ess_charge_power_limit" not in sent


def test_ha_source_select_still_uses_plant_flat():
    """EcoFlow bridge: plant-flat set_ess_source_select remains allowed."""
    from optimizer import powerstation_live as psl

    adapter = MagicMock()
    adapter.cfg.entities = {"set_ess_source_select": "switch.delta_3_grid_bypass"}
    adapter.cfg.adapter_id = "ha-test"
    adapter.write_mapped_fields = MagicMock(return_value=None)
    persisted: list = []

    with patch.object(psl, "_planning_powerstations", return_value=[]), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "runtime_store.shadow.writes.should_invoke_setpoint_writes", return_value=True
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=True
    ), patch(
        "integrations.ehal_live.get_ha_adapter", return_value=adapter
    ), patch(
        "integrations.ehal_live.persist_write_error", side_effect=persisted.append
    ):
        psl.write_standby_source_selects({"delta3": 1})

    adapter.write_mapped_fields.assert_called_once_with({"set_ess_source_select": 1.0})
    assert persisted == []


def test_cycle_powerstation_charge_kw_defaults_idle_mapped_pack():
    """Idle physical PS with charge binding gets 0 every cycle (sticky refresh)."""
    from optimizer import powerstation_live as psl

    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "backing": "physical",
            "role": ROLE_STANDBY_BACKUP,
            "ehal_bindings": {
                ess_field(slug, "set_ess_charge_power_limit"): "PS_Charge",
            },
        }
    ]
    with patch.object(psl, "_planning_powerstations", return_value=planning):
        out = psl.cycle_powerstation_charge_kw({}, {})
    assert out == {slug: 0.0}


def test_cycle_standby_source_selects_defaults_grid_when_bound():
    """Idle standby_backup with Quellenwahl binding refreshes to grid (0)."""
    from optimizer import powerstation_live as psl

    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "backing": "physical",
            "role": ROLE_STANDBY_BACKUP,
            "ehal_bindings": {},
        }
    ]
    with patch.object(psl, "_planning_powerstations", return_value=planning), patch(
        "house_config.ehal_bindings.resolve_plant_binding",
        return_value="Earnie_Speicher_Quellenwahl",
    ), patch(
        "optimizer.live_export_limit.load_house_doc", return_value={}
    ):
        out = psl.cycle_standby_source_selects({})
    assert out == {slug: SOURCE_GRID}


def test_cycle_writes_idle_zero_charge_to_loxone():
    """Every-cycle path sends charge 0 when no reserve/standby charge."""
    from ehal.ess_fields import ess_field
    from optimizer import powerstation_live as psl

    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "backing": "physical",
            "role": ROLE_STANDBY_BACKUP,
            "ehal_bindings": {
                ess_field(slug, "set_ess_charge_power_limit"): "PS_Charge",
            },
        }
    ]
    with patch.object(psl, "_planning_powerstations", return_value=planning), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "runtime_store.shadow.writes.should_invoke_setpoint_writes", return_value=True
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=False
    ), patch(
        "integrations.ehal_live.is_ehal_network_backend", return_value=False
    ), patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as send:
        send.return_value = MagicMock(success=True)
        charges = psl.cycle_powerstation_charge_kw({}, {})
        psl.write_physical_powerstation_charges(charges)

    send.assert_called_once()
    assert send.call_args[0][0] == ess_field(slug, "set_ess_charge_power_limit")
    assert send.call_args[0][1] == pytest.approx(0.0)
    assert send.call_args.kwargs.get("io_name") == "PS_Charge"


def test_build_cycle_powerstation_fields_all_mapped_setpoints():
    """Idle cycle includes every mapped set_* with safe defaults."""
    from optimizer import powerstation_live as psl

    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "backing": "physical",
            "role": ROLE_STANDBY_BACKUP,
            "ehal_bindings": {
                ess_field(slug, "set_ess_charge_power_limit"): "PS_Charge",
                ess_field(slug, "set_ess_discharge_power_limit"): "PS_Discharge",
                ess_field(slug, "set_ess_mode"): "PS_Mode",
                ess_field(slug, "set_ess_active_power"): "PS_Active",
            },
        }
    ]
    with patch.object(psl, "_planning_powerstations", return_value=planning), patch(
        "house_config.ehal_bindings.resolve_plant_binding", return_value=""
    ), patch(
        "optimizer.live_export_limit.load_house_doc", return_value={}
    ):
        fields = psl.build_cycle_powerstation_fields({slug: 0.5}, {})

    assert fields[ess_field(slug, "set_ess_charge_power_limit")] == pytest.approx(500.0)
    assert fields[ess_field(slug, "set_ess_discharge_power_limit")] == 0.0
    assert fields[ess_field(slug, "set_ess_mode")] == 0.0
    assert fields[ess_field(slug, "set_ess_active_power")] == 0.0


def test_planned_powerstation_loxone_sent_merker_wire_no_publish():
    """Silent snapshot helper: Merker keys + kW wire; never publishes."""
    from optimizer import powerstation_live as psl

    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "backing": "physical",
            "role": ROLE_STANDBY_BACKUP,
            "ehal_bindings": {
                ess_field(slug, "set_ess_charge_power_limit"): "PS_Charge",
                ess_field(slug, "set_ess_mode"): "PS_Mode",
            },
        }
    ]
    with patch.object(psl, "_planning_powerstations", return_value=planning), patch(
        "house_config.ehal_bindings.resolve_plant_binding", return_value=""
    ), patch(
        "optimizer.live_export_limit.load_house_doc", return_value={}
    ), patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as send:
        sent = psl.planned_powerstation_loxone_sent({slug: 0.5}, {})

    send.assert_not_called()
    assert sent["PS_Charge"] == pytest.approx(0.5)
    assert sent["PS_Mode"] == pytest.approx(0.0)


def test_write_cycle_powerstation_setpoints_returns_records():
    """Cycle writer sends all mapped Merkers and returns Live-Schreiben records."""
    from integrations.loxone_comm_trace import LoxoneWriteRecord
    from optimizer import powerstation_live as psl

    slug = "ecoflow_delta_3"
    planning = [
        {
            "id": slug,
            "type": "powerstation",
            "backing": "physical",
            "role": ROLE_STANDBY_BACKUP,
            "ehal_bindings": {
                ess_field(slug, "set_ess_charge_power_limit"): "PS_Charge",
                ess_field(slug, "set_ess_mode"): "PS_Mode",
                ess_field(slug, "set_ess_active_power"): "PS_Active",
            },
        }
    ]
    with patch.object(psl, "_planning_powerstations", return_value=planning), patch(
        "optimizer.powerstation_live.config.is_loxone_silent_mode", return_value=False
    ), patch(
        "runtime_store.shadow.writes.should_invoke_setpoint_writes", return_value=True
    ), patch(
        "integrations.ehal_live.is_ha_backend", return_value=False
    ), patch(
        "integrations.ehal_live.is_ehal_network_backend", return_value=False
    ), patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as send:
        send.side_effect = lambda qid, val, *, io_name="": LoxoneWriteRecord(
            io_name or qid, float(val), True, "2026-10-07T10:00:00"
        )
        records = psl.write_cycle_powerstation_setpoints({slug: 0.0}, {})

    names = {r.io_name for r in records}
    assert names == {"PS_Charge", "PS_Mode", "PS_Active"}
    assert len(records) == 3
