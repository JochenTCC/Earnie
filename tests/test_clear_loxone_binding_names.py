"""Q8: clear Merker names from Loxone bindings (keep activation keys)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ehal.functions import available_functions, function_statuses
from house_config.clear_loxone_binding_names import (
    clear_binding_values,
    clear_loxone_binding_names_in_components,
    clear_loxone_binding_names_in_house,
)


def test_clear_binding_values() -> None:
    assert clear_binding_values({"sens_pv_production_active": "PV", "x": ""}) == {
        "sens_pv_production_active": "",
        "x": "",
    }


def test_clear_house_and_components() -> None:
    house = {
        "plant": {"ehal_bindings": {"sens_pv_production_active": "PV"}},
        "profiles": {
            "live": {
                "consumers": [
                    {
                        "id": "wm",
                        "ehal_bindings": {"flex.wm.set_enable": "En"},
                    }
                ]
            }
        },
    }
    cleared = clear_loxone_binding_names_in_house(house)
    assert cleared["plant"]["ehal_bindings"]["sens_pv_production_active"] == ""
    assert cleared["profiles"]["live"]["consumers"][0]["ehal_bindings"][
        "flex.wm.set_enable"
    ] == ""
    # original untouched
    assert house["plant"]["ehal_bindings"]["sens_pv_production_active"] == "PV"

    house_list = {
        "plant": {"ehal_bindings": {"sens_pv_production_active": "PV"}},
        "profiles": [
            {
                "id": "live",
                "consumers": [
                    {"id": "wm", "ehal_bindings": {"flex.wm.set_enable": "En"}}
                ],
            }
        ],
    }
    cleared_list = clear_loxone_binding_names_in_house(house_list)
    assert cleared_list["profiles"][0]["consumers"][0]["ehal_bindings"][
        "flex.wm.set_enable"
    ] == ""

    components = {
        "batteries": [
            {
                "id": "b1",
                "ehal_bindings": {"ess.b1.sens_ess_soc": "SoC"},
            }
        ]
    }
    cleared_c = clear_loxone_binding_names_in_components(components)
    assert cleared_c["batteries"][0]["ehal_bindings"]["ess.b1.sens_ess_soc"] == ""


def test_mapped_fields_empty_loxone_activation() -> None:
    mapped = {
        "sens_grid_power_active": "",
        "sens_pv_production_active": "",
        "sens_ess_soc": "",
    }
    assert available_functions(mapped, require_nonempty_value=False) >= {"telemetry"}
    assert available_functions(mapped, require_nonempty_value=True) == set()
    statuses = function_statuses(mapped, require_nonempty_value=False)
    tele = next(s for s in statuses if s.function.id == "telemetry")
    assert tele.state == "available"


def test_empty_ess_activation_resolves_plant_flat_aliases(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q8 clear of Merker titles must not drop primary ESS resolve (Live-Cockpit)."""
    from ehal.ess_fields import ess_field
    from house_config.ehal_bindings import resolve_plant_binding

    house_id = "15_kwh_speicher"
    components = {
        "batteries": [
            {
                "id": house_id,
                "type": "house",
                "ehal_bindings": {
                    ess_field(house_id, "sens_ess_soc"): "",
                    ess_field(house_id, "set_ess_active_power"): "",
                    ess_field(house_id, "set_ess_charge_power_limit"): "",
                    ess_field(house_id, "set_ess_discharge_power_limit"): "",
                    ess_field(house_id, "set_ess_mode"): "",
                },
            }
        ]
    }
    path = tmp_path / "components.json"
    path.write_text(json.dumps(components), encoding="utf-8")
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(path))
    monkeypatch.setattr(
        "runtime_store.persist_paths.resolve_components_json_path",
        lambda: str(path),
    )

    house = {"plant": {"ehal_bindings": {}}}
    assert resolve_plant_binding(house, "sens_ess_soc") == "sens_ess_soc"
    assert resolve_plant_binding(house, "set_ess_mode") == "set_ess_mode"


def test_empty_thermal_rc_activation_uses_pool_namespace() -> None:
    """MILP flex must keep type=thermal_rc so Ist-Temperatur reads pool.* not consumer.*."""
    from house_config.planning_flex_converters import planning_thermal_rc_to_milp
    from settings.ehal_marker_resolve import marker_sens_temperature_water

    house_row = {
        "id": "pool_swimspa",
        "label": "Pool",
        "type": "thermal_rc",
        "nominal_power_kw": 2.8,
        "thermal_rc": {
            "water_volume_liters": 5900,
            "setpoint_c": 36.0,
            "tolerance_c": 1.0,
            "heat_loss_kw_per_k": 0.1,
            "heating_efficiency": 0.95,
        },
        "ehal_bindings": {"sens_temperature_water": ""},
    }
    milp = planning_thermal_rc_to_milp(house_row)
    assert milp["type"] == "thermal_rc"
    assert (
        marker_sens_temperature_water(milp)
        == "pool.pool_swimspa.sens_temperature_water"
    )


def test_empty_activation_resolves_write_qids() -> None:
    from house_config.ehal_bindings import resolve_plant_binding
    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    flex = {
        "id": "wm",
        "type": "generic",
        "ehal_bindings": {"flex.wm.set_enable": ""},
    }
    assert marker_flex_enable(flex) == "consumer.wm.set_enable"

    pool = {
        "id": "pool_swimspa",
        "type": "thermal_rc",
        "ehal_bindings": {"pool.pool_swimspa.set_enable": ""},
    }
    assert marker_flex_enable(pool) == "pool.pool_swimspa.set_enable"

    ev = {
        "id": "e_auto",
        "type": "ev",
        "ehal_bindings": {
            "set_evcs_max_current": "",
            "set_evcs_mode": "",
        },
    }
    assert marker_set_evcs_max_current(ev) == "evcs.e_auto.set_evcs_max_current"
    assert marker_set_evcs_mode(ev) == "evcs.e_auto.set_evcs_mode"

    house = {
        "plant": {"ehal_bindings": {"set_grid_export_power_limit": ""}},
    }
    assert (
        resolve_plant_binding(house, "set_grid_export_power_limit")
        == "grid.meter.set_grid_export_power_limit"
    )


def test_empty_grid_read_activation_resolves_qualified_exchange_id() -> None:
    """Empty plant Merker must resolve to grid.meter.* (push inbox / Live-Lesen)."""
    from house_config.ehal_bindings import resolve_plant_binding

    house = {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
                "get_grid_export_power_limit": "",
            }
        }
    }
    assert (
        resolve_plant_binding(house, "sens_grid_power_active")
        == "grid.meter.sens_grid_power_active"
    )
    assert (
        resolve_plant_binding(house, "get_grid_export_power_limit")
        == "grid.meter.get_grid_export_power_limit"
    )


def test_empty_activation_flex_publish_uses_qid() -> None:
    from integrations.loxone_comm_trace import LoxoneWriteRecord
    from integrations.loxone_writes import _publish_flexible_consumer_outputs

    consumer = {
        "id": "wm",
        "name": "WM",
        "type": "generic",
        "ehal_bindings": {"flex.wm.set_enable": ""},
    }
    published: list[tuple[str, float, str]] = []

    def _pub(qid, value, *, io_name=""):
        published.append((qid, float(value), io_name))
        return LoxoneWriteRecord(
            io_name=io_name or qid,
            value=float(value),
            success=True,
            written_at="2026-10-10T00:00:00",
        )

    with patch(
        "integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub
    ):
        records = _publish_flexible_consumer_outputs(
            consumer, {"consumer.wm.set_enable": 1.0}
        )
    assert len(records) == 1
    assert published == [("consumer.wm.set_enable", 1.0, "consumer.wm.set_enable")]


def test_q8_empty_battery_write_io_indexes_qid(tmp_path, monkeypatch) -> None:
    """Q8 empty Merker must still appear in setpoint IO index (Pattern B)."""
    from ehal.ess_fields import ess_field
    from integrations.ehal_debug_mapping import build_loxone_setpoint_io_index

    house_id = "15_kwh_speicher"
    components = {
        "batteries": [
            {
                "id": house_id,
                "type": "house",
                "ehal_bindings": {
                    ess_field(house_id, "set_ess_active_power"): "",
                    ess_field(house_id, "set_ess_charge_power_limit"): "",
                    ess_field(house_id, "set_ess_discharge_power_limit"): "",
                    ess_field(house_id, "set_ess_mode"): "",
                },
            }
        ]
    }
    path = tmp_path / "components.json"
    path.write_text(json.dumps(components), encoding="utf-8")
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(path))
    monkeypatch.setattr(
        "runtime_store.persist_paths.resolve_components_json_path",
        lambda: str(path),
    )
    index = build_loxone_setpoint_io_index()
    qid = ess_field(house_id, "set_ess_mode")
    assert index.get(qid) == qid


def test_ess_c1_publishes_pattern_b_when_batteries_present() -> None:
    """House ESS C1 must publish ess.<id>.set_* after Q8 (not plant-flat Merker)."""
    from integrations import loxone_client as lc
    from integrations.loxone_comm_trace import LoxoneWriteRecord
    from integrations import loxone_writes as lw

    names = {
        "LOXONE_TARGET_ACTIVE_POWER_NAME": "set_ess_active_power",
        "LOXONE_TARGET_CHARGE_POWER_NAME": "set_ess_charge_power_limit",
        "LOXONE_TARGET_DISCHARGE_POWER_NAME": "set_ess_discharge_power_limit",
        "LOXONE_CONTROL_CMD_NAME": "set_ess_mode",
    }
    fake = LoxoneWriteRecord(
        io_name="x", value=0.0, success=True, written_at="t"
    )
    with (
        patch.object(lc.config, "get", side_effect=lambda n, **k: names.get(n)),
        patch.object(
            lc.config,
            "get_battery_params",
            return_value={
                "max_power_kw": 5.0,
                "max_charge_power_kw": 5.0,
                "max_discharge_power_kw": 5.0,
            },
        ),
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=True,
        ),
        patch(
            "integrations.loxone_adapter.primary_ess_id_for_plant_read",
            return_value="15_kwh_speicher",
        ),
        patch(
            "integrations.ehal_debug_mapping.build_loxone_setpoint_io_index",
            return_value={},
        ),
        patch.object(lw, "_publish_setpoint_traced", return_value=fake) as pub,
    ):
        records = lw.send_huawei_modbus_states(0, 0.0, 0.0)

    assert len(records) == 4
    qids = [c.args[0] for c in pub.call_args_list]
    assert qids == [
        "ess.15_kwh_speicher.set_ess_active_power",
        "ess.15_kwh_speicher.set_ess_charge_power_limit",
        "ess.15_kwh_speicher.set_ess_discharge_power_limit",
        "ess.15_kwh_speicher.set_ess_mode",
    ]
    assert [c.kwargs.get("io_name") for c in pub.call_args_list] == qids


def test_live_schreiben_maps_bare_ess_trace_to_pattern_b() -> None:
    """Write-trace bare set_ess_* must match Live Pattern B rows after Q8."""
    import ui.loxone_debug  # noqa: F401 — load before rows (avoids circular import)
    from ui.loxone_debug_rows import build_write_rows_from_trace

    qid = "ess.15_kwh_speicher.set_ess_mode"
    with (
        patch(
            "ui.loxone_debug_rows.build_loxone_setpoint_io_index",
            return_value={qid: qid},
        ),
        patch(
            "ui.loxone_debug_rows.loxone_write_field_to_io",
            return_value={qid: qid},
        ),
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=True,
        ),
        patch(
            "integrations.loxone_adapter.primary_ess_id_for_plant_read",
            return_value="15_kwh_speicher",
        ),
    ):
        rows = build_write_rows_from_trace(
            [
                {
                    "io_name": "set_ess_mode",
                    "value": 0.0,
                    "success": True,
                    "written_at": "t",
                }
            ],
            expected_fields=[qid],
        )
    assert len(rows) == 1
    assert rows[0]["EHAL-Feld"] == qid
    assert rows[0]["Erfolg"] == "Ja"
    assert rows[0]["Meldung"] == ""


def test_normalize_battery_keeps_q8_empty_activation_keys() -> None:
    """Planning must retain empty ehal_bindings keys (PS write activation)."""
    from house_config.entity_resolution import normalize_battery

    raw = {
        "id": "ecoflow_delta_3",
        "type": "powerstation",
        "battery_capacity_kwh": 1.0,
        "battery_max_charge_power_kw": 1.0,
        "battery_max_discharge_power_kw": 0.0,
        "battery_efficiency": 0.94,
        "battery_min_soc": 5.0,
        "battery_max_soc": 100.0,
        "backing": "physical",
        "role": "standby_backup",
        "ehal_bindings": {
            "ess.ecoflow_delta_3.set_ess_mode": "",
            "ess.ecoflow_delta_3.set_ess_charge_power_limit": "",
        },
    }
    out = normalize_battery(raw, 0)
    assert out["ehal_bindings"]["ess.ecoflow_delta_3.set_ess_mode"] == ""
    assert (
        out["ehal_bindings"]["ess.ecoflow_delta_3.set_ess_charge_power_limit"] == ""
    )


def test_empty_activation_binding_for_ps_returns_qid() -> None:
    from optimizer import powerstation_live as psl

    ps = {
        "id": "ecoflow_delta_3",
        "ehal_bindings": {
            "ess.ecoflow_delta_3.set_ess_charge_power_limit": "",
        },
    }
    with patch.object(psl, "_planning_powerstations", return_value=[ps]):
        assert (
            psl._binding_for_ps("ecoflow_delta_3", "set_ess_charge_power_limit")
            == "ess.ecoflow_delta_3.set_ess_charge_power_limit"
        )


def test_try_marker_write_allows_empty_display_merker() -> None:
    from integrations.loxone_adapter import LoxoneAdapter, LoxoneConfig
    from integrations.loxone_comm_trace import LoxoneWriteRecord

    adapter = LoxoneAdapter(
        LoxoneConfig(
            adapter_id="loxone-home",
            active_power_name="Active",
            control_cmd_name="Cmd",
        )
    )
    pub = MagicMock(
        return_value=LoxoneWriteRecord(
            io_name="set_ess_mode",
            value=0.0,
            success=True,
            written_at="2026-10-10T00:00:00",
        )
    )
    with patch("integrations.loxone_writes._publish_setpoint_traced", pub):
        ok, msg = adapter._try_marker_write("", 0.0, field="set_ess_mode")
    assert ok and msg == ""
    pub.assert_called_once_with("set_ess_mode", 0.0, io_name="set_ess_mode")
