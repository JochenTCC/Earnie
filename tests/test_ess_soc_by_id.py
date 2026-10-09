"""Refuse planning without own ESS SoC (2.7.n-1 / Backlog-Bugfixes)."""
from __future__ import annotations

from unittest.mock import patch

from ehal.ess_fields import ess_field
from integrations import ehal_live
from optimizer.powerstation_standby import plan_standby_horizon


def test_read_ess_soc_by_id_no_primary_fallback_for_second_battery():
    """Second battery with missing binding must not inherit primary SoC."""
    ehal_live._soc_missing_warned.clear()
    batteries = [
        {
            "id": "house",
            "type": "house",
            "ehal_bindings": {ess_field("house", "sens_ess_soc"): "House_SoC"},
        },
        {
            "id": "pack_b",
            "type": "house",
            "ehal_bindings": {},
        },
    ]

    def _read(addr: str):
        if addr == "House_SoC":
            return 55.0
        return None

    with patch.object(ehal_live, "_mappable_batteries_for_soc", return_value=batteries), patch.object(
        ehal_live, "read_ess_soc", return_value=55.0
    ), patch.object(ehal_live, "_read_soc_from_address", side_effect=_read):
        by_id = ehal_live.read_ess_soc_by_id()

    assert by_id == {"house": 55.0}
    assert "pack_b" not in by_id


def test_read_ess_soc_by_id_primary_plant_alias():
    """Primary may use plant sens_ess_soc when own binding is empty."""
    ehal_live._soc_missing_warned.clear()
    batteries = [
        {"id": "house", "type": "house", "ehal_bindings": {}},
    ]
    with patch.object(ehal_live, "_mappable_batteries_for_soc", return_value=batteries), patch.object(
        ehal_live, "read_ess_soc", return_value=42.0
    ), patch.object(ehal_live, "_read_soc_from_address", return_value=None):
        by_id = ehal_live.read_ess_soc_by_id()

    assert by_id == {"house": 42.0}


def test_read_ess_soc_by_id_warns_once_per_battery(caplog):
    ehal_live._soc_missing_warned.clear()
    batteries = [
        {"id": "house", "type": "house", "ehal_bindings": {}},
        {
            "id": "delta3",
            "type": "powerstation",
            "backing": "physical",
            "ehal_bindings": {},
        },
    ]
    with patch.object(ehal_live, "_mappable_batteries_for_soc", return_value=batteries), patch.object(
        ehal_live, "read_ess_soc", return_value=50.0
    ), patch.object(ehal_live, "_read_soc_from_address", return_value=None), caplog.at_level(
        "WARNING"
    ):
        ehal_live.read_ess_soc_by_id()
        ehal_live.read_ess_soc_by_id()

    warnings = [r for r in caplog.records if "delta3" in r.getMessage()]
    assert len(warnings) == 1


def test_filter_planning_batteries_with_soc_drops_missing():
    batteries = [
        {"id": "a", "battery_capacity_kwh": 10},
        {"id": "b", "battery_capacity_kwh": 5},
    ]
    kept = ehal_live.filter_planning_batteries_with_soc(batteries, {"a": 40.0})
    assert [b["id"] for b in kept] == ["a"]


def test_plan_standby_skips_pack_without_soc():
    matrix = [
        {"k_act": 0.05, "expected_p_act": 1.0, "expected_p_pv": 0.0},
        {"k_act": 0.40, "expected_p_act": 1.0, "expected_p_pv": 0.0},
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
    plans = plan_standby_horizon(matrix, packs, current_soc_by_id={}, dt_h=0.25)
    assert plans == {}
