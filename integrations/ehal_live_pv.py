"""Live PV attribution and house-load derive (split from ``ehal_live``).

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to the
façade (``config``, adapters, ``collect_scoped_pv_live_w``, ...) stay effective.
"""
from __future__ import annotations

from typing import Any

from integrations.ehal_live_ref import live


def _plant_from_house_profiles() -> dict:
    try:
        from integrations.pv_attribution import load_house_for_attribution

        house = load_house_for_attribution()
        plant = house.get("plant") if isinstance(house, dict) else None
        return plant if isinstance(plant, dict) else {}
    except Exception:  # noqa: BLE001 — derive must stay usable in tests
        return {}


def derive_sens_power_consumers_w(
    telemetry: dict[str, Any],
    *,
    plant_pv_w: float,
    plant: dict | None = None,
) -> float:
    """House load W: mapped value if present, else PV + grid + ESS with P2 tolerance."""
    from integrations.plant_balance import (
        balance_tolerances_from_plant,
        derive_sens_power_consumers_w as derive_balanced,
    )

    plant_map = plant if isinstance(plant, dict) else live._plant_from_house_profiles()
    pct, watts = balance_tolerances_from_plant(plant_map)
    return derive_balanced(
        telemetry,
        plant_pv_w=plant_pv_w,
        tolerance_pct=pct,
        tolerance_w=watts,
    )


def with_derived_sens_power_consumers(
    telemetry: dict[str, Any],
    *,
    plant_pv_w: float,
    plant: dict | None = None,
) -> dict[str, Any]:
    """Return a copy with sens_power_consumers filled when missing/null."""
    out = dict(telemetry)
    if out.get("sens_power_consumers") is None:
        out["sens_power_consumers"] = live.derive_sens_power_consumers_w(
            out, plant_pv_w=plant_pv_w, plant=plant
        )
    return out


def collect_scoped_pv_live_w() -> dict[str, float]:
    """Mapped ``inv.*.sens_inv_power_pv`` / ``pv.*.sens_pv_production_active`` live W."""
    from integrations.pv_attribution import (
        collect_scoped_pv_live_from_bindings,
        load_components_for_attribution,
        read_scoped_pv_ha,
        read_scoped_pv_loxone,
    )

    components = load_components_for_attribution()
    backend = str(live.config.get("EHAL_BACKEND") or "loxone").strip().lower()
    if backend == "ha":
        return collect_scoped_pv_live_from_bindings(
            components, read_value=read_scoped_pv_ha
        )
    if backend == "loxone":
        return collect_scoped_pv_live_from_bindings(
            components, read_value=read_scoped_pv_loxone
        )
    return {}


def with_live_pv_attribution(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Fill missing ``inv.*.sens_inv_power_pv`` from complete per-PV maps.

    Does not write bare plant ``sens_pv_production_active`` (retired from telemetry).
    """
    from integrations.pv_attribution import (
        load_components_for_attribution,
        with_attributed_plant_pv,
    )

    components = load_components_for_attribution()
    inverters = list(components.get("inverters") or [])
    pv_systems = list(components.get("pv_systems") or [])
    scoped = live.collect_scoped_pv_live_w()
    # Prefer values already on telemetry (tests / adapters) over fresh reads.
    for key, value in telemetry.items():
        key_s = str(key)
        if (
            key_s.startswith("inv.") and key_s.endswith(".sens_inv_power_pv")
        ) or (
            key_s.startswith("pv.") and key_s.endswith(".sens_pv_production_active")
        ):
            if value is not None:
                scoped[key_s] = max(0.0, float(value))
    return with_attributed_plant_pv(
        telemetry,
        scoped_live=scoped,
        inverters=inverters,
        pv_systems=pv_systems,
    )


def plant_pv_ac_w_live(telemetry: dict[str, Any]) -> float:
    """Plant AC PV W from scoped inv/pv on ``telemetry`` (OpenEMS: _sum channel)."""
    from integrations.pv_attribution import (
        derive_plant_pv_ac_w,
        grid_tied_inverters_with_pv,
        load_components_for_attribution,
        plant_pv_derive_coverage_complete,
        scoped_pv_live_from_telemetry,
    )

    components = load_components_for_attribution()
    inverters = list(components.get("inverters") or [])
    pv_systems = list(components.get("pv_systems") or [])
    scoped = scoped_pv_live_from_telemetry(telemetry)
    scoped.update(live.collect_scoped_pv_live_w())
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if not eligible:
        return 0.0
    if plant_pv_derive_coverage_complete(
        inverters, pv_systems, scoped_live=scoped
    ):
        return derive_plant_pv_ac_w(scoped, inverters, pv_systems)
    backend = str(live.config.get("EHAL_BACKEND") or "loxone").strip().lower()
    if backend == "openems":
        return live._openems_production_ac_w()
    return derive_plant_pv_ac_w(scoped, inverters, pv_systems)


def _openems_production_ac_w() -> float:
    """OpenEMS ``_sum/ProductionActivePower`` as plant AC PV (already AC)."""
    adapter = live.get_openems_adapter()
    raw = adapter.read_channel("_sum", "ProductionActivePower")
    if raw is None:
        raise ValueError(
            "OpenEMS ProductionActivePower missing; map inv.*.sens_inv_power_pv "
            "or ensure _sum/ProductionActivePower is available."
        )
    return max(0.0, float(raw))


def prepare_live_telemetry(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Post-read: inv/pv attribution then house-load derive from plant AC PV."""
    attributed = live.with_live_pv_attribution(telemetry)
    plant_pv = live.plant_pv_ac_w_live(attributed)
    return live.with_derived_sens_power_consumers(attributed, plant_pv_w=plant_pv)
