"""Closed-loop house physics: SoC, PV, grid, energy counters, optional thermal."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .archetype import ArchetypePackage, StateWriter, project_physics_to_store
from .thermal import simulate_next_temp_c


@dataclass(frozen=True)
class EssSetpoints:
    """Battery setpoints for one tick (EHAL: + discharge, − charge)."""

    active_power_w: float = 0.0
    charge_limit_w: float | None = None
    discharge_limit_w: float | None = None


@dataclass
class ScenarioOverlay:
    """Transient scenario knobs; durations decay with each ``step_physics`` call."""

    cloud_pass_remaining_h: float = 0.0
    cloud_pass_scale: float = 0.2
    load_spike_remaining_h: float = 0.0
    load_spike_extra_kw: float = 0.0
    evcs_power_override_w: float | None = None

    def decay(self, dt_h: float) -> None:
        self.cloud_pass_remaining_h = max(0.0, self.cloud_pass_remaining_h - dt_h)
        self.load_spike_remaining_h = max(0.0, self.load_spike_remaining_h - dt_h)

    def apply_cloud_pass(self, *, minutes: float, scale: float = 0.2) -> None:
        self.cloud_pass_remaining_h = max(0.0, float(minutes) / 60.0)
        self.cloud_pass_scale = float(scale)

    def apply_load_spike(self, *, minutes: float, extra_kw: float) -> None:
        self.load_spike_remaining_h = max(0.0, float(minutes) / 60.0)
        self.load_spike_extra_kw = float(extra_kw)

    def car_arrives(self, power_w: float = 7000.0) -> None:
        self.evcs_power_override_w = float(power_w)

    def car_leaves(self) -> None:
        self.evcs_power_override_w = 0.0


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


def resolve_ess_power_w(setpoints: EssSetpoints) -> float:
    value = float(setpoints.active_power_w)
    if value < 0 and setpoints.charge_limit_w is not None:
        value = max(value, -abs(float(setpoints.charge_limit_w)))
    if value > 0 and setpoints.discharge_limit_w is not None:
        value = min(value, abs(float(setpoints.discharge_limit_w)))
    return value


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
    setpoints: EssSetpoints,
    dt_h: float,
    overlay: ScenarioOverlay | None = None,
    pv_kw_override: float | None = None,
) -> PhysicsState:
    """Advance house physics by Δt hours using explicit setpoints."""
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    capacity_kwh = float(package.house_params.get("battery_capacity_kwh", 0.0))
    if capacity_kwh <= 0:
        raise ValueError("battery_capacity_kwh must be > 0")

    next_tick = state.tick + 1
    if pv_kw_override is not None:
        pv_kw = float(pv_kw_override)
    else:
        pv_kw = _pv_at_tick(package.pv_series_kw, next_tick)

    if overlay is not None and overlay.cloud_pass_remaining_h > 0:
        pv_kw = pv_kw * float(overlay.cloud_pass_scale)

    ess_power_w = resolve_ess_power_w(setpoints)
    ess_kw = ess_power_w / 1000.0
    soc = state.soc_pct - (ess_kw * dt_h / capacity_kwh) * 100.0
    soc = max(0.0, min(100.0, soc))

    load_kw = float(package.house_params.get("load_kw", state.load_kw))
    if overlay is not None and overlay.load_spike_remaining_h > 0:
        load_kw = load_kw + float(overlay.load_spike_extra_kw)

    if overlay is not None and overlay.evcs_power_override_w is not None:
        evcs_power_w = float(overlay.evcs_power_override_w)
    else:
        evcs_power_w = float(state.evcs_power_w)
    load_kw = load_kw + evcs_power_w / 1000.0

    grid_kw = load_kw - pv_kw + ess_kw
    grid_power_w = grid_kw * 1000.0

    pv_delta = max(0.0, float(pv_kw)) * float(dt_h)
    import_delta = max(0.0, float(grid_kw)) * float(dt_h)
    export_delta = max(0.0, -float(grid_kw)) * float(dt_h)

    temp_c = state.temp_c
    ambient_c = state.ambient_c
    thermal = package.house_params.get("thermal")
    if isinstance(thermal, dict) and temp_c is not None and ambient_c is not None:
        heat_kw = float(thermal.get("heat_kw", 0.0))
        next_1h = simulate_next_temp_c(
            float(temp_c),
            float(ambient_c),
            heat_kw,
            capacity_kwh_per_k=float(thermal["capacity_kwh_per_k"]),
            heat_loss_kw_per_k=float(thermal["heat_loss_kw_per_k"]),
            heating_efficiency=float(thermal.get("heating_efficiency", 1.0)),
        )
        temp_c = float(temp_c) + (float(next_1h) - float(temp_c)) * float(dt_h)

    if overlay is not None:
        overlay.decay(dt_h)

    return replace(
        state,
        tick=next_tick,
        soc_pct=soc,
        pv_kw=pv_kw,
        ess_power_w=ess_power_w,
        grid_power_w=grid_power_w,
        load_kw=load_kw,
        evcs_power_w=evcs_power_w,
        pv_energy_kwh=state.pv_energy_kwh + pv_delta,
        grid_import_energy_kwh=state.grid_import_energy_kwh + import_delta,
        grid_export_energy_kwh=state.grid_export_energy_kwh + export_delta,
        temp_c=temp_c,
        ambient_c=ambient_c,
    )


def run_ticks(
    package: ArchetypePackage,
    store: StateWriter,
    *,
    n_ticks: int,
    dt_h: float,
    physics: PhysicsState | None = None,
    setpoints: EssSetpoints | None = None,
    overlay: ScenarioOverlay | None = None,
    read_setpoints=None,
) -> PhysicsState:
    """Run n closed-loop ticks; project physics onto the store after each step.

    ``read_setpoints`` if provided is ``callable(store, package) -> EssSetpoints``
    and is called before each tick (mock adapter). Otherwise ``setpoints`` is reused.
    """
    state = physics or initial_physics(package)
    project_physics_to_store(store, package=package, physics=state.as_dict())
    current = setpoints or EssSetpoints()
    for _ in range(int(n_ticks)):
        if read_setpoints is not None:
            current = read_setpoints(store, package)
        state = step_physics(
            state,
            package=package,
            setpoints=current,
            dt_h=dt_h,
            overlay=overlay,
        )
        project_physics_to_store(store, package=package, physics=state.as_dict())
    return state
