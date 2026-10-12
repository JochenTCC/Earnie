"""η_inv / η_batt split: migrate, resolve η_path, PV · η_inv."""
from __future__ import annotations

import pytest

from house_config.entity_resolution import (
    battery_params_from_planning,
    resolve_components_into_settings,
)
from house_config.inverter import (
    DEFAULT_INVERTER_EFFICIENCY,
    needs_conversion_efficiency_migration,
    normalize_inverter,
    reject_if_needs_conversion_efficiency_migration,
)
from house_config.migrate_conversion_efficiency import (
    migrate_components_conversion_efficiency,
)
from optimizer.milp_inverter import ac_clip_pv_and_max_discharge, apply_dc_pv_cap
from tests.config_fixtures import main_hybrid_inverter


def _components(*, eta_inv: float | None = 0.97, eta_batt: float = 0.97) -> dict:
    inv = main_hybrid_inverter()
    if eta_inv is None:
        inv.pop("efficiency", None)
    else:
        inv["efficiency"] = eta_inv
    return {
        "inverters": [inv],
        "batteries": [
            {
                "id": "house",
                "label": "Haus",
                "inverter_id": "wr_main",
                "battery_capacity_kwh": 10.0,
                "battery_max_charge_power_kw": 5.0,
                "battery_max_discharge_power_kw": 5.0,
                "battery_efficiency": eta_batt,
                "battery_min_soc": 10.0,
                "battery_max_soc": 100.0,
                "threshold_power": 0.02,
                "control": "full",
                "regulates_on": "grid",
                "ehal_bindings": {},
            }
        ],
        "pv_systems": [
            {
                "id": "pv1",
                "label": "PV",
                "kwp": 10.0,
                "pv_tilt": 30.0,
                "pv_azimuth": 0.0,
                "inverter_id": "wr_main",
            }
        ],
    }


def test_needs_migration_when_efficiency_missing() -> None:
    doc = _components(eta_inv=None)
    assert needs_conversion_efficiency_migration(doc) is True
    with pytest.raises(ValueError, match="efficiency"):
        reject_if_needs_conversion_efficiency_migration(doc)


def test_migrate_rewrites_eta_batt() -> None:
    doc = _components(eta_inv=None, eta_batt=0.97)
    out, changed = migrate_components_conversion_efficiency(doc)
    assert changed is True
    assert out["inverters"][0]["efficiency"] == DEFAULT_INVERTER_EFFICIENCY
    assert out["batteries"][0]["battery_efficiency"] == pytest.approx(
        0.97 / DEFAULT_INVERTER_EFFICIENCY
    )
    assert needs_conversion_efficiency_migration(out) is False


def test_normalize_inverter_requires_efficiency() -> None:
    raw = main_hybrid_inverter()
    raw.pop("efficiency")
    with pytest.raises(ValueError, match="efficiency"):
        normalize_inverter(raw, 0)


def test_resolve_path_efficiency_product() -> None:
    doc = _components(eta_inv=0.97, eta_batt=0.95)
    settings = resolve_components_into_settings(
        {"battery_ids": ["house"], "pv_system_ids": ["pv1"]},
        doc,
    )
    entry = settings["_planning_batteries"][0]
    assert entry["inverter_efficiency"] == pytest.approx(0.97)
    assert entry["battery_efficiency"] == pytest.approx(0.95)
    params = battery_params_from_planning(entry)
    assert params["efficiency"] == pytest.approx(0.97 * 0.95)


def test_pv_ac_applies_eta_inv_then_clip() -> None:
    inv = main_hybrid_inverter(efficiency=0.9, max_ac_power_kw=5.0)
    pv_dc = apply_dc_pv_cap(10.0, inv)
    pv_ac, max_dis = ac_clip_pv_and_max_discharge(pv_dc, inv)
    assert pv_ac == pytest.approx(5.0)  # 10 * 0.9 = 9, then clip to 5
    assert max_dis == pytest.approx(0.0)

    inv2 = main_hybrid_inverter(efficiency=0.9)  # no AC cap
    pv_ac2, max_dis2 = ac_clip_pv_and_max_discharge(10.0, inv2)
    assert pv_ac2 == pytest.approx(9.0)
    assert max_dis2 is None
