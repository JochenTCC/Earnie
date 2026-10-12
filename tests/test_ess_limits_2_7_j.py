"""2.7.j ESS limits: migrate, resolve live vs HK, asymmetric map_ess_setpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from house_config.entity_resolution import normalize_battery, split_battery_max_power_kw
from integrations.loxone_writes import map_ess_setpoints
from optimizer import battery as bat
from settings.ess_limits_resolve import apply_effective_ess_limits, resolve_effective_ess_limits


def test_split_legacy_battery_max_power_kw():
    charge, discharge = split_battery_max_power_kw({"battery_max_power_kw": 4.0})
    assert charge == 4.0
    assert discharge == 4.0


def test_normalize_battery_migrates_legacy_and_limits_from_live():
    spec = normalize_battery(
        {
            "id": "b1",
            "inverter_id": "wr_main",
            "battery_capacity_kwh": 10.0,
            "battery_max_power_kw": 5.0,
            "battery_efficiency": 0.95,
            "battery_min_soc": 10.0,
            "battery_max_soc": 90.0,
            "limits_from_live": True,
            "regulates_on": "grid",
            "battery_wear": {"enabled": False},
        },
        0,
    )
    assert spec["battery_max_charge_power_kw"] == 5.0
    assert spec["battery_max_discharge_power_kw"] == 5.0
    assert spec["battery_max_power_kw"] == 5.0
    assert spec["limits_from_live"] is True


def test_normalize_battery_asymmetric_charge_discharge():
    spec = normalize_battery(
        {
            "id": "b1",
            "inverter_id": "wr_main",
            "battery_capacity_kwh": 10.0,
            "battery_max_charge_power_kw": 3.0,
            "battery_max_discharge_power_kw": 7.0,
            "battery_efficiency": 0.95,
            "battery_min_soc": 10.0,
            "battery_max_soc": 90.0,
            "regulates_on": "grid",
            "battery_wear": {"enabled": False},
        },
        0,
    )
    assert spec["battery_max_charge_power_kw"] == 3.0
    assert spec["battery_max_discharge_power_kw"] == 7.0
    assert spec["battery_max_power_kw"] == 7.0


def test_resolve_effective_ess_limits_hk_when_flag_off():
    params = {
        "min_soc": 15.0,
        "max_soc": 85.0,
        "max_charge_power_kw": 4.0,
        "max_discharge_power_kw": 6.0,
        "limits_from_live": False,
    }
    telemetry = {
        "get_ess_soc_min": 20.0,
        "get_ess_soc_max": 80.0,
        "get_ess_max_charge_power": 2000.0,
        "get_ess_max_discharge_power": 8000.0,
    }
    out = resolve_effective_ess_limits(params, telemetry=telemetry)
    assert out["min_soc"] == 15.0
    assert out["max_soc"] == 85.0
    assert out["max_charge_power_kw"] == 4.0
    assert out["max_discharge_power_kw"] == 6.0


def test_resolve_effective_ess_limits_live_when_flag_on():
    params = {
        "min_soc": 15.0,
        "max_soc": 85.0,
        "max_charge_power_kw": 4.0,
        "max_discharge_power_kw": 6.0,
        "limits_from_live": True,
    }
    telemetry = {
        "get_ess_soc_min": 20.0,
        "get_ess_soc_max": 80.0,
        "get_ess_max_charge_power": 2000.0,
        "get_ess_max_discharge_power": 8000.0,
    }
    out = resolve_effective_ess_limits(params, telemetry=telemetry)
    assert out["min_soc"] == 20.0
    assert out["max_soc"] == 80.0
    assert out["max_charge_power_kw"] == 2.0
    assert out["max_discharge_power_kw"] == 8.0
    assert out["max_power_kw"] == 8.0


def test_resolve_effective_ess_limits_fallback_when_unmapped():
    params = {
        "min_soc": 15.0,
        "max_soc": 85.0,
        "max_charge_power_kw": 4.0,
        "max_discharge_power_kw": 6.0,
        "limits_from_live": True,
    }
    out = resolve_effective_ess_limits(params, telemetry={})
    assert out["min_soc"] == 15.0
    assert out["max_charge_power_kw"] == 4.0
    assert out["max_discharge_power_kw"] == 6.0


def test_apply_effective_ess_limits_preserves_other_keys():
    params = {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 90.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "efficiency": 0.97,
        "control": "full",
        "limits_from_live": False,
    }
    out = apply_effective_ess_limits(params, telemetry=None)
    assert out["battery_capacity_kwh"] == 10.0
    assert out["efficiency"] == 0.97
    assert out["control"] == "full"


@pytest.mark.parametrize(
    ("mode", "target", "charge_max", "discharge_max", "active", "charge", "discharge", "cmd"),
    [
        (bat.MODE_ZWANGS_LADEN, 3.0, 5.0, 7.0, -3.0, 5.0, 0.0, 1),
        (bat.MODE_ENTLADESPERRE, 0.0, 5.0, 7.0, None, 5.0, 0.0, 1),
        (bat.MODE_ZWANGS_ENTLADEN, 4.0, 5.0, 7.0, 4.0, 0.0, 7.0, 2),
        (bat.MODE_AUTOMATIK, 0.0, 5.0, 7.0, None, 5.0, 7.0, 0),
    ],
)
def test_map_ess_setpoints_asymmetric(
    mode, target, charge_max, discharge_max, active, charge, discharge, cmd
):
    assert map_ess_setpoints(mode, target, charge_max, discharge_max) == (
        active,
        charge,
        discharge,
        cmd,
    )


def test_map_ess_setpoints_legacy_single_max():
    assert map_ess_setpoints(bat.MODE_AUTOMATIK, 0.0, 5.0) == (None, 5.0, 5.0, 0)


def test_plant_live_read_fields_include_ess_gets():
    from integrations.ehal_debug_mapping import PLANT_LIVE_READ_FIELDS

    for field in (
        "get_ess_soc_min",
        "get_ess_soc_max",
        "get_ess_max_charge_power",
        "get_ess_max_discharge_power",
    ):
        assert field in PLANT_LIVE_READ_FIELDS


def test_collect_read_checks_includes_ess_limit_gets(tmp_path, monkeypatch):
    from ehal.ess_fields import ess_field
    from integrations import loxone_connectivity as lc

    from tests.config_fixtures import main_hybrid_inverter

    house_id = "15_kwh_speicher"
    components = {
        "inverters": [main_hybrid_inverter()],
        "batteries": [
            {
                "id": house_id,
                "type": "house",
                "inverter_id": "wr_main",
                "battery_capacity_kwh": 15.0,
                "battery_max_charge_power_kw": 5.0,
                "battery_max_discharge_power_kw": 5.0,
                "battery_efficiency": 0.97,
                "battery_min_soc": 10.0,
                "battery_max_soc": 100.0,
                "regulates_on": "grid",
                "ehal_bindings": {
                    ess_field(house_id, "get_ess_soc_min"): "Earnie_Batterie_SOC_Min",
                    ess_field(house_id, "get_ess_soc_max"): "Earnie_Batterie_SOC_Max",
                    ess_field(
                        house_id, "get_ess_max_charge_power"
                    ): "Earnie_Batterie_Max_Ladeleistung",
                    ess_field(
                        house_id, "get_ess_max_discharge_power"
                    ): "Earnie_Batterie_Max_Entladeleistung",
                },
            }
        ],
        "pv_systems": [],
    }
    path = tmp_path / "components.json"
    path.write_text(__import__("json").dumps(components), encoding="utf-8")
    monkeypatch.setattr(
        "runtime_store.persist_paths.resolve_components_json_path",
        lambda: str(path),
    )
    house = {"plant": {"ehal_bindings": {}}}

    with patch.object(
        lc.config, "get_flexible_consumers", return_value=[]
    ), patch.object(
        lc.config.CONFIG, "get_resolved_runtime_settings", return_value={}
    ), patch.object(
        lc.loxone_client, "_default_house_profiles_doc", return_value=house
    ):
        checks = lc.collect_read_checks()

    by_label = {label: io for label, io, _ in checks}
    assert by_label[ess_field(house_id, "get_ess_soc_min")] == "Earnie_Batterie_SOC_Min"
    assert by_label[ess_field(house_id, "get_ess_soc_max")] == "Earnie_Batterie_SOC_Max"
    assert (
        by_label[ess_field(house_id, "get_ess_max_charge_power")]
        == "Earnie_Batterie_Max_Ladeleistung"
    )
    assert (
        by_label[ess_field(house_id, "get_ess_max_discharge_power")]
        == "Earnie_Batterie_Max_Entladeleistung"
    )


def test_live_unconstrained_uses_discharge_side(monkeypatch):
    import config
    from optimizer.live_export_limit import live_unconstrained_export_kw

    params = {
        "max_charge_power_kw": 3.0,
        "max_discharge_power_kw": 9.0,
        "max_power_kw": 9.0,
        "control": "full",
    }
    monkeypatch.setattr(config, "get_battery_params", lambda: params)
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [params])
    monkeypatch.setattr(config, "get", lambda name, default=None, cast=None: 10.0)
    assert live_unconstrained_export_kw() == pytest.approx(19.0)
