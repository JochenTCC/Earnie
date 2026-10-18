"""Topology P2: ESS sum, load tolerance, multi-inv plant-PV derive, η_inv fail-loud."""
from __future__ import annotations

import pytest

from ehal.ess_fields import ess_field
from ehal.inverter_fields import inv_field
from house_config.profiles_store import _normalize_plant
from integrations.plant_balance import (
    DEFAULT_BALANCE_TOLERANCE_PCT,
    DEFAULT_BALANCE_TOLERANCE_W,
    derive_sens_power_consumers_w,
    sum_grid_tied_house_ess_power_w,
)
from integrations.pv_attribution import _eta_inv, with_attributed_plant_pv


def _house_bat(bat_id: str, *, inv_id: str = "wr_main") -> dict:
    return {
        "id": bat_id,
        "type": "house",
        "inverter_id": inv_id,
        "regulates_on": "grid",
        "ehal_bindings": {},
    }


def _hybrid(inv_id: str = "wr_main", *, ac: str = "grid_tied") -> dict:
    return {
        "id": inv_id,
        "type": "hybrid",
        "ac_connection": ac,
        "control": "full",
        "efficiency": 0.97,
        "ehal_bindings": {},
    }


def test_sum_ess_single_and_multi() -> None:
    batteries = [_house_bat("a"), _house_bat("b", inv_id="wr_b")]
    inverters = [_hybrid("wr_main"), _hybrid("wr_b")]
    values = {"a": 100.0, "b": -50.0}

    def _read(bid: str) -> float | None:
        return values.get(bid)

    assert sum_grid_tied_house_ess_power_w(
        batteries=batteries[:1],
        inverters=inverters,
        read_power_w=_read,
    ) == pytest.approx(100.0)
    assert sum_grid_tied_house_ess_power_w(
        batteries=batteries,
        inverters=inverters,
        read_power_w=_read,
    ) == pytest.approx(50.0)


def test_sum_ess_missing_binding_raises() -> None:
    batteries = [_house_bat("a"), _house_bat("b", inv_id="wr_b")]
    inverters = [_hybrid("wr_main"), _hybrid("wr_b")]

    def _read(bid: str) -> float | None:
        return 10.0 if bid == "a" else None

    with pytest.raises(ValueError, match=ess_field("b", "sens_ess_power")):
        sum_grid_tied_house_ess_power_w(
            batteries=batteries,
            inverters=inverters,
            read_power_w=_read,
        )


def test_sum_ess_battery_less_is_zero() -> None:
    assert (
        sum_grid_tied_house_ess_power_w(
            batteries=[],
            inverters=[_hybrid()],
            read_power_w=lambda _bid: 999.0,
        )
        == 0.0
    )


def test_sum_ess_excludes_island_bus_battery() -> None:
    batteries = [
        _house_bat("home"),
        _house_bat("island", inv_id="wr_island"),
    ]
    inverters = [_hybrid("wr_main"), _hybrid("wr_island", ac="island")]

    def _read(bid: str) -> float | None:
        return {"home": 200.0, "island": 5000.0}.get(bid)

    assert sum_grid_tied_house_ess_power_w(
        batteries=batteries,
        inverters=inverters,
        read_power_w=_read,
    ) == pytest.approx(200.0)


def test_derive_load_within_tolerance_clamps_to_zero() -> None:
    # P_PV=1000 → floor = -max(100, 0.05*1000) = -100
    telem = {
        "sens_pv_production_active": 1000.0,
        "sens_grid_power_active": -900.0,
        "sens_ess_power": -50.0,  # raw = 50 → ok
    }
    assert derive_sens_power_consumers_w(telem) == pytest.approx(50.0)
    telem_neg = {
        "sens_pv_production_active": 1000.0,
        "sens_grid_power_active": -1050.0,
        "sens_ess_power": 0.0,  # raw = -50 → within floor → 0
    }
    assert derive_sens_power_consumers_w(telem_neg) == pytest.approx(0.0)


def test_derive_load_below_floor_raises() -> None:
    telem = {
        "sens_pv_production_active": 1000.0,
        "sens_grid_power_active": -1200.0,
        "sens_ess_power": 0.0,  # raw = -200 < -100
    }
    with pytest.raises(ValueError, match="House balance telemetry error"):
        derive_sens_power_consumers_w(telem)


def test_derive_load_night_uses_absolute_floor() -> None:
    # P_PV=0 → floor = -100 W
    telem_ok = {
        "sens_pv_production_active": 0.0,
        "sens_grid_power_active": -50.0,
        "sens_ess_power": 0.0,
    }
    assert derive_sens_power_consumers_w(telem_ok) == pytest.approx(0.0)
    telem_bad = {
        "sens_pv_production_active": 0.0,
        "sens_grid_power_active": -150.0,
        "sens_ess_power": 0.0,
    }
    with pytest.raises(ValueError, match="House balance telemetry error"):
        derive_sens_power_consumers_w(telem_bad)


def test_multi_inv_ignores_mapped_plant_and_derives_sum() -> None:
    inverters = [
        {
            "id": "wr_a",
            "ac_connection": "grid_tied",
            "efficiency": 1.0,
            "ehal_bindings": {},
        },
        {
            "id": "wr_b",
            "ac_connection": "grid_tied",
            "efficiency": 1.0,
            "ehal_bindings": {},
        },
    ]
    pv_systems = [
        {"id": "p1", "inverter_id": "wr_a", "ehal_bindings": {}},
        {"id": "p2", "inverter_id": "wr_b", "ehal_bindings": {}},
    ]
    with pytest.raises(ValueError, match="incomplete"):
        with_attributed_plant_pv(
            {"sens_pv_production_active": 3000.0},
            scoped_live={},
            inverters=inverters,
            pv_systems=pv_systems,
        )
    scoped = {
        inv_field("wr_a", "sens_inv_power_pv"): 1000.0,
        inv_field("wr_b", "sens_inv_power_pv"): 2000.0,
    }
    out = with_attributed_plant_pv(
        {"sens_pv_production_active": 9999.0},
        scoped_live=scoped,
        inverters=inverters,
        pv_systems=pv_systems,
    )
    assert out["sens_pv_production_active"] == pytest.approx(3000.0)


def test_eta_inv_raises_when_efficiency_missing() -> None:
    with pytest.raises(ValueError, match="efficiency"):
        _eta_inv({"id": "wr", "ac_connection": "grid_tied"})


def test_normalize_plant_p2_fields() -> None:
    out = _normalize_plant(
        {
            "pv_covers_all_inverters": True,
            "balance_tolerance_pct": 7,
            "balance_tolerance_w": 50,
        }
    )
    assert "pv_covers_all_inverters" not in out
    assert out["balance_tolerance_pct"] == pytest.approx(7.0)
    assert out["balance_tolerance_w"] == pytest.approx(50.0)
    empty = _normalize_plant({})
    assert "pv_covers_all_inverters" not in empty
    assert "balance_tolerance_pct" not in empty
    assert DEFAULT_BALANCE_TOLERANCE_PCT == 5.0
    assert DEFAULT_BALANCE_TOLERANCE_W == 100.0
