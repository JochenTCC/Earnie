"""Multi-inverter live PV attribution + first pv.* namespace."""
from __future__ import annotations

import pytest

from ehal.pv_fields import pv_field, pv_field_kind
from ehal.qualified_ids import NS_PV, qualified_pv_id
from ehal.inverter_fields import inv_field
from integrations.pv_attribution import (
    attribute_plant_pv_to_inverters_w,
    derive_plant_pv_ac_w,
    fill_inv_pv_from_pv_systems,
    plant_pv_derive_coverage_complete,
    with_attributed_plant_pv,
)


def _inv(iid: str, *, eta: float = 0.97, ac: str = "grid_tied") -> dict:
    return {
        "id": iid,
        "type": "hybrid",
        "ac_connection": ac,
        "efficiency": eta,
        "ehal_bindings": {},
    }


def _pv(pid: str, inv_id: str, *, bindings: dict | None = None) -> dict:
    out = {
        "id": pid,
        "kwp": 5.0,
        "inverter_id": inv_id,
        "ehal_bindings": bindings or {},
    }
    return out


def test_pv_field_helpers() -> None:
    assert pv_field("roof", "sens_pv_production_active") == (
        "pv.roof.sens_pv_production_active"
    )
    assert pv_field_kind("pv.roof.sens_pv_production_active") == (
        "sens_pv_production_active"
    )
    assert qualified_pv_id("roof", "sens_pv_production_active") == (
        "pv.roof.sens_pv_production_active"
    )
    assert NS_PV == "pv"


def test_derive_plant_from_full_inv_maps_excludes_island() -> None:
    inverters = [
        _inv("wr_a", eta=1.0),
        _inv("wr_island", eta=1.0, ac="island"),
    ]
    # Binding keys present (push-only activation) so coverage is complete.
    inverters[0]["ehal_bindings"] = {
        inv_field("wr_a", "sens_inv_power_pv"): ""
    }
    pv_systems = [
        _pv("p1", "wr_a"),
        _pv("p2", "wr_island"),
    ]
    scoped = {
        inv_field("wr_a", "sens_inv_power_pv"): 1000.0,
        inv_field("wr_island", "sens_inv_power_pv"): 5000.0,
    }
    assert plant_pv_derive_coverage_complete(inverters, pv_systems)
    plant = derive_plant_pv_ac_w(scoped, inverters, pv_systems)
    assert plant == pytest.approx(1000.0)


def test_derive_plant_applies_eta_inv_once() -> None:
    inverters = [_inv("wr", eta=0.9)]
    pv_systems = [_pv("p1", "wr")]
    scoped = {inv_field("wr", "sens_inv_power_pv"): 1000.0}
    assert derive_plant_pv_ac_w(scoped, inverters, pv_systems) == pytest.approx(900.0)


def test_derive_inv_from_full_pv_maps() -> None:
    inverters = [_inv("wr", eta=1.0)]
    pv_systems = [
        _pv("a", "wr"),
        _pv("b", "wr"),
    ]
    scoped = {
        pv_field("a", "sens_pv_production_active"): 400.0,
        pv_field("b", "sens_pv_production_active"): 600.0,
    }
    filled = fill_inv_pv_from_pv_systems(scoped, inverters, pv_systems)
    assert filled[inv_field("wr", "sens_inv_power_pv")] == pytest.approx(1000.0)
    plant = derive_plant_pv_ac_w(filled, inverters, pv_systems)
    assert plant == pytest.approx(1000.0)


def test_fail_loud_partial_inv_coverage() -> None:
    inverters = [_inv("wr_a"), _inv("wr_b")]
    pv_systems = [_pv("p1", "wr_a"), _pv("p2", "wr_b")]
    scoped = {inv_field("wr_a", "sens_inv_power_pv"): 1000.0}
    assert not plant_pv_derive_coverage_complete(inverters, pv_systems)
    with pytest.raises(ValueError, match="incomplete"):
        derive_plant_pv_ac_w(scoped, inverters, pv_systems)


def test_fail_loud_partial_pv_maps_when_deriving_plant() -> None:
    inverters = [_inv("wr", eta=1.0)]
    pv_systems = [_pv("a", "wr"), _pv("b", "wr")]
    scoped = {pv_field("a", "sens_pv_production_active"): 400.0}
    with pytest.raises(ValueError, match="partial PV"):
        with_attributed_plant_pv(
            {},
            scoped_live=scoped,
            inverters=inverters,
            pv_systems=pv_systems,
        )


def test_split_helper_proportional_to_live_ac_weights() -> None:
    inverters = [_inv("wr_a", eta=1.0), _inv("wr_b", eta=1.0)]
    pv_systems = [_pv("p1", "wr_a"), _pv("p2", "wr_b")]
    scoped = {
        inv_field("wr_a", "sens_inv_power_pv"): 1000.0,
        inv_field("wr_b", "sens_inv_power_pv"): 3000.0,
    }
    allocated = attribute_plant_pv_to_inverters_w(
        4000.0,
        scoped_live=scoped,
        inverters=inverters,
        pv_systems=pv_systems,
    )
    assert allocated["wr_a"] == pytest.approx(1000.0)
    assert allocated["wr_b"] == pytest.approx(3000.0)
    assert sum(allocated.values()) == pytest.approx(4000.0)


def test_with_attributed_keeps_mapped_plant() -> None:
    inverters = [_inv("wr")]
    pv_systems = [_pv("p1", "wr")]
    out = with_attributed_plant_pv(
        {"sens_pv_production_active": 2500.0},
        scoped_live={},
        inverters=inverters,
        pv_systems=pv_systems,
    )
    assert out["sens_pv_production_active"] == pytest.approx(2500.0)


def test_curtail_allocation_still_forecast_only() -> None:
    """Live attribution helper must not be wired into curtail weights yet."""
    import inspect

    from optimizer import inv_ac_power_limit

    src = inspect.getsource(inv_ac_power_limit.allocate_inv_ac_limits_kw)
    assert "attribute_plant_pv_to_inverters" not in src
    assert "raw_pv_kw_by_inverter" in src
