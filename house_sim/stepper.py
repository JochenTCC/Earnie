"""Short closed-loop physics: SoC coulomb counter, PV series, optional thermal."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from house_sim.archetype import ArchetypePackage
from house_sim.state_store import StateStore


@dataclass(frozen=True)
class PhysicsState:
    tick: int
    soc_pct: float
    pv_kw: float
    ess_power_w: float
    grid_power_w: float
    load_kw: float
    evcs_power_w: float
    pv_energy_kwh: float
    grid_import_energy_kwh: float
    grid_export_energy_kwh: float
    temp_c: float | None
    ambient_c: float | None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "tick": self.tick,
            "soc_pct": self.soc_pct,
            "pv_kw": self.pv_kw,
            "ess_power_w": self.ess_power_w,
            "grid_power_w": self.grid_power_w,
            "load_kw": self.load_kw,
            "evcs_power_w": self.evcs_power_w,
            "pv_energy_kwh": self.pv_energy_kwh,
            "grid_import_energy_kwh": self.grid_import_energy_kwh,
            "grid_export_energy_kwh": self.grid_export_energy_kwh,
        }
        if self.temp_c is not None:
            out["temp_c"] = self.temp_c
        if self.ambient_c is not None:
            out["ambient_c"] = self.ambient_c
        return out


def _fixture_energy_kwh(package: ArchetypePackage, field: str, default: float) -> float:
    entity_id = str(package.ehal_entities.get(field) or "").strip()
    if not entity_id:
        return float(default)
    for item in package.entities:
        if str(item.get("entity_id") or "").strip() != entity_id:
            continue
        try:
            return float(str(item.get("state") or default).replace(",", "."))
        except ValueError:
            return float(default)
    return float(default)


def initial_physics(package: ArchetypePackage) -> PhysicsState:
    params = package.house_params
    thermal = params.get("thermal") if isinstance(params.get("thermal"), dict) else None
    return PhysicsState(
        tick=0,
        soc_pct=float(params.get("initial_soc_pct", 50.0)),
        pv_kw=float(package.pv_series_kw[0]),
        ess_power_w=0.0,
        grid_power_w=0.0,
        load_kw=float(params.get("load_kw", 1.0)),
        evcs_power_w=float(params.get("initial_evcs_power_w", 0.0)),
        pv_energy_kwh=_fixture_energy_kwh(package, "sens_pv_energy", 0.0),
        grid_import_energy_kwh=_fixture_energy_kwh(
            package, "sens_grid_energy_import", 0.0
        ),
        grid_export_energy_kwh=_fixture_energy_kwh(
            package, "sens_grid_energy_export", 0.0
        ),
        temp_c=float(thermal["initial_temp_c"]) if thermal else None,
        ambient_c=float(thermal["ambient_c"]) if thermal else None,
    )


def _resolve_ess_power_w(store: StateStore, package: ArchetypePackage) -> float:
    """EHAL signed W from last written setpoints (+ discharge, − charge)."""
    entities = package.ehal_entities
    active_id = entities.get("set_ess_active_power")
    if active_id:
        active = store.numeric_state(active_id)
        if active is not None:
            charge_cap = store.numeric_state(
                entities.get("set_ess_charge_power_limit") or ""
            )
            discharge_cap = store.numeric_state(
                entities.get("set_ess_discharge_power_limit") or ""
            )
            value = float(active)
            if value < 0 and charge_cap is not None:
                value = max(value, -abs(float(charge_cap)))
            if value > 0 and discharge_cap is not None:
                value = min(value, abs(float(discharge_cap)))
            return value
    return 0.0


def _pv_at_tick(series: list[float], tick: int) -> float:
    if tick < 0:
        return float(series[0])
    if tick >= len(series):
        return float(series[-1])
    return float(series[tick])


def step_physics(
    state: PhysicsState,
    *,
    package: ArchetypePackage,
    store: StateStore,
    dt_h: float,
) -> PhysicsState:
    """Advance house physics by Δt hours using last setpoints in the store."""
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    capacity_kwh = float(package.house_params.get("battery_capacity_kwh", 0.0))
    if capacity_kwh <= 0:
        raise ValueError("battery_capacity_kwh must be > 0")

    next_tick = state.tick + 1
    pv_kw = _pv_at_tick(package.pv_series_kw, next_tick)
    ess_power_w = _resolve_ess_power_w(store, package)
    # EHAL: + discharge drains SoC; − charge raises SoC
    ess_kw = ess_power_w / 1000.0
    soc = state.soc_pct - (ess_kw * dt_h / capacity_kwh) * 100.0
    soc = max(0.0, min(100.0, soc))

    load_kw = float(package.house_params.get("load_kw", state.load_kw))
    # Balance: load = pv + grid_import − ess_discharge_equiv
    # ess_kw > 0 (discharge) supplies load; ess_kw < 0 (charge) adds to load
    grid_kw = load_kw - pv_kw + ess_kw
    grid_power_w = grid_kw * 1000.0

    # Cumulative energy (total_increasing): ∫P·Δt over this tick
    pv_delta = max(0.0, float(pv_kw)) * float(dt_h)
    import_delta = max(0.0, float(grid_kw)) * float(dt_h)
    export_delta = max(0.0, -float(grid_kw)) * float(dt_h)

    temp_c = state.temp_c
    ambient_c = state.ambient_c
    thermal = package.house_params.get("thermal")
    if isinstance(thermal, dict) and temp_c is not None and ambient_c is not None:
        from optimizer.thermal_model import simulate_next_temp_c

        heat_kw = float(thermal.get("heat_kw", 0.0))
        # Scale Euler step: simulate_next_temp_c is defined for 1 h; apply dt_h factor
        # by calling with heat/loss over the fraction of an hour via linear Euler.
        next_1h = simulate_next_temp_c(
            float(temp_c),
            float(ambient_c),
            heat_kw,
            capacity_kwh_per_k=float(thermal["capacity_kwh_per_k"]),
            heat_loss_kw_per_k=float(thermal["heat_loss_kw_per_k"]),
            heating_efficiency=float(thermal.get("heating_efficiency", 1.0)),
        )
        # Interpolate for sub-hour ticks: temp += (next_1h - temp) * dt_h
        temp_c = float(temp_c) + (float(next_1h) - float(temp_c)) * float(dt_h)

    return replace(
        state,
        tick=next_tick,
        soc_pct=soc,
        pv_kw=pv_kw,
        ess_power_w=ess_power_w,
        grid_power_w=grid_power_w,
        load_kw=load_kw,
        pv_energy_kwh=state.pv_energy_kwh + pv_delta,
        grid_import_energy_kwh=state.grid_import_energy_kwh + import_delta,
        grid_export_energy_kwh=state.grid_export_energy_kwh + export_delta,
        temp_c=temp_c,
        ambient_c=ambient_c,
    )


def run_ticks(
    package: ArchetypePackage,
    store: StateStore,
    *,
    n_ticks: int,
    dt_h: float,
    physics: PhysicsState | None = None,
) -> PhysicsState:
    """Run n closed-loop ticks; project physics onto the store after each step."""
    from house_sim.archetype import project_physics_to_store

    state = physics or initial_physics(package)
    project_physics_to_store(store, package=package, physics=state.as_dict())
    for _ in range(int(n_ticks)):
        state = step_physics(state, package=package, store=store, dt_h=dt_h)
        project_physics_to_store(store, package=package, physics=state.as_dict())
    return state
