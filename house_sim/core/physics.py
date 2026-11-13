"""Closed-loop house physics: SoC, PV, grid, energy counters, optional thermal."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping

from .archetype import (
    ArchetypePackage,
    StateWriter,
    battery_energy_entity_id,
    entity_unit,
    native_to_base,
    project_physics_to_store,
)
from .evcs import (
    EvcsEvent,
    EvcsState,
    WallboxSetpoints,
    apply_events,
    has_wallbox_model,
    initial_evcs_state,
    parse_evs,
    parse_wallboxes,
    step_evcs,
)
from .evcs import wallbox_setpoints_from_lookup as _wallbox_setpoints_from_lookup
from .thermal import simulate_next_temp_c


@dataclass(frozen=True)
class EssSetpoints:
    """Battery setpoints for one tick (EHAL: + discharge, − charge).

    ``self_consumption``: the archetype has no active-power setpoint entity, so
    the battery follows PV surplus / house deficit within the limits (typical
    vendor default mode, e.g. Huawei "Maximise self consumption").
    """

    active_power_w: float = 0.0
    charge_limit_w: float | None = None
    discharge_limit_w: float | None = None
    self_consumption: bool = False


def ess_setpoints_from_lookup(
    package: ArchetypePackage,
    lookup: Callable[[str], float | None],
) -> EssSetpoints:
    """Build setpoints from mapped entities; ``lookup(entity_id)`` returns the
    raw numeric state in the entity's own unit (W or kW)."""
    entities = package.ehal_entities

    def _watts(field: str) -> float | None:
        entity_id = entities.get(field)
        if not entity_id:
            return None
        raw = lookup(entity_id)
        if raw is None:
            return None
        return native_to_base(float(raw), quantity="power", unit=entity_unit(package, entity_id))

    fallback = str(package.house_params.get("ess_fallback") or "").strip().lower()
    self_consumption = not entities.get("set_ess_active_power") and fallback == "self_consumption"
    return EssSetpoints(
        active_power_w=float(_watts("set_ess_active_power") or 0.0),
        charge_limit_w=_watts("set_ess_charge_power_limit"),
        discharge_limit_w=_watts("set_ess_discharge_power_limit"),
        self_consumption=self_consumption,
    )


def wallbox_setpoints_from_lookup(
    package: ArchetypePackage,
    numeric: Callable[[str], float | None],
    text: Callable[[str], str | None],
) -> dict[str, WallboxSetpoints]:
    """Wallbox setpoints from mapped vendor entities (``house_params.wallboxes``).

    ``numeric(entity_id)`` returns the raw number, ``text(entity_id)`` the raw
    state string. The current entity must be in A (or carry no unit).
    """
    wallboxes = parse_wallboxes(package.house_params)
    for wallbox in wallboxes:
        entity_id = wallbox.entities.max_current
        if entity_id and entity_unit(package, entity_id) not in ("", "a"):
            raise ValueError(f"Wallbox {wallbox.id!r}: {entity_id} must be in A")
    return _wallbox_setpoints_from_lookup(wallboxes, numeric=numeric, text=text)


@dataclass
class ScenarioOverlay:
    """Transient scenario knobs; durations decay with each ``step_physics`` call."""

    cloud_pass_remaining_h: float = 0.0
    cloud_pass_scale: float = 0.2
    load_spike_remaining_h: float = 0.0
    load_spike_extra_kw: float = 0.0
    evcs_power_override_w: float | None = None
    evcs_events: list[EvcsEvent] = field(default_factory=list)

    def decay(self, dt_h: float) -> None:
        self.cloud_pass_remaining_h = max(0.0, self.cloud_pass_remaining_h - dt_h)
        self.load_spike_remaining_h = max(0.0, self.load_spike_remaining_h - dt_h)

    def apply_cloud_pass(self, *, minutes: float, scale: float = 0.2) -> None:
        self.cloud_pass_remaining_h = max(0.0, float(minutes) / 60.0)
        self.cloud_pass_scale = float(scale)

    def apply_load_spike(self, *, minutes: float, extra_kw: float) -> None:
        self.load_spike_remaining_h = max(0.0, float(minutes) / 60.0)
        self.load_spike_extra_kw = float(extra_kw)

    def car_arrives(
        self,
        power_w: float = 7000.0,
        *,
        wallbox: str | None = None,
        ev: str | None = None,
        soc_pct: float | None = None,
    ) -> None:
        """Plug a car in.

        With ``wallbox`` and ``ev`` (archetype with ``house_params.wallboxes``) the
        EV is plugged into that wallbox at the next tick and charges by setpoint.
        Without them (archetype without a wallbox model) the wallbox draws the
        fixed ``power_w``.
        """
        if wallbox is None and ev is None:
            self.evcs_power_override_w = float(power_w)
            return
        if not wallbox or not ev:
            raise ValueError("car_arrives needs both wallbox and ev")
        self.evcs_events.append(EvcsEvent(wallbox_id=wallbox, ev_id=ev, soc_pct=soc_pct))

    def car_leaves(self, *, wallbox: str | None = None) -> None:
        """Unplug the car at ``wallbox``; without it, end the fixed power override."""
        if wallbox is None:
            self.evcs_power_override_w = 0.0
            return
        self.evcs_events.append(EvcsEvent(wallbox_id=wallbox, ev_id=None))


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
    ess_charge_energy_kwh: float = 0.0
    ess_discharge_energy_kwh: float = 0.0
    # Wallbox model (``house_params.wallboxes``); empty for archetypes without it.
    evcs: EvcsState = field(default_factory=EvcsState)

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
            "ess_charge_energy_kwh": self.ess_charge_energy_kwh,
            "ess_discharge_energy_kwh": self.ess_discharge_energy_kwh,
        }
        if self.temp_c is not None:
            out["temp_c"] = self.temp_c
        if self.ambient_c is not None:
            out["ambient_c"] = self.ambient_c
        if self.evcs.wallbox_power_w or self.evcs.ev_soc_pct:
            out["evcs"] = self.evcs.as_dict()
        return out


def _fixture_energy_kwh(package: ArchetypePackage, field: str, default: float) -> float:
    entity_id = str(package.ehal_entities.get(field) or "").strip()
    return _fixture_state_kwh(package, entity_id, default)


def _fixture_state_kwh(package: ArchetypePackage, entity_id: str, default: float) -> float:
    """Initial counter in kWh (fixture state may be in Wh)."""
    if not entity_id:
        return float(default)
    for item in package.entities:
        if str(item.get("entity_id") or "").strip() != entity_id:
            continue
        try:
            raw = float(str(item.get("state") or default).replace(",", "."))
        except ValueError:
            return float(default)
        return native_to_base(raw, quantity="energy", unit=entity_unit(package, entity_id))
    return float(default)


def initial_physics(package: ArchetypePackage) -> PhysicsState:
    params = package.house_params
    thermal = params.get("thermal") if isinstance(params.get("thermal"), dict) else None
    evcs = EvcsState()
    if has_wallbox_model(params):
        if float(params.get("initial_evcs_power_w", 0.0)):
            raise ValueError(
                "initial_evcs_power_w does not apply with house_params.wallboxes; "
                "plug an EV in with initial_ev_id instead"
            )
        wallboxes = parse_wallboxes(params)
        evcs = initial_evcs_state(
            wallboxes,
            parse_evs(params),
            initial_energy_kwh={
                w.id: _fixture_state_kwh(package, w.entities.energy or "", 0.0)
                for w in wallboxes
            },
        )
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
        ess_charge_energy_kwh=_fixture_state_kwh(
            package, battery_energy_entity_id(package, "charge"), 0.0
        ),
        ess_discharge_energy_kwh=_fixture_state_kwh(
            package, battery_energy_entity_id(package, "discharge"), 0.0
        ),
        evcs=evcs,
    )


def _step_wallboxes(
    state: PhysicsState,
    *,
    package: ArchetypePackage,
    overlay: ScenarioOverlay | None,
    wallbox_setpoints: Mapping[str, WallboxSetpoints] | None,
    dt_h: float,
) -> tuple[float, EvcsState]:
    """Wallbox power (W) for this tick and the new wallbox / EV state."""
    params = package.house_params
    if not has_wallbox_model(params):
        if overlay is not None and overlay.evcs_events:
            raise ValueError(
                "car_arrives / car_leaves with a wallbox need house_params.wallboxes"
            )
        if overlay is not None and overlay.evcs_power_override_w is not None:
            return float(overlay.evcs_power_override_w), state.evcs
        return float(state.evcs_power_w), state.evcs

    if overlay is not None and overlay.evcs_power_override_w is not None:
        raise ValueError(
            "This archetype models its wallboxes (house_params.wallboxes): "
            "use car_arrives(wallbox=..., ev=...) instead of a fixed power"
        )
    wallboxes = parse_wallboxes(params)
    evs = parse_evs(params)
    evcs = state.evcs
    if overlay is not None and overlay.evcs_events:
        # Take the events first: a bad event must not repeat on every tick.
        events = list(overlay.evcs_events)
        overlay.evcs_events.clear()
        evcs = apply_events(evcs, events, wallboxes=wallboxes, evs=evs)
    evcs = step_evcs(
        evcs, wallboxes=wallboxes, evs=evs, setpoints=wallbox_setpoints, dt_h=dt_h
    )
    return evcs.total_power_w, evcs


def resolve_ess_power_w(setpoints: EssSetpoints) -> float:
    value = float(setpoints.active_power_w)
    if value < 0 and setpoints.charge_limit_w is not None:
        value = max(value, -abs(float(setpoints.charge_limit_w)))
    if value > 0 and setpoints.discharge_limit_w is not None:
        value = min(value, abs(float(setpoints.discharge_limit_w)))
    return value


def _cap_w(explicit: float | None, params: dict[str, Any], key: str) -> float:
    """Charge/discharge cap from a mapped limit, else an explicit house param.

    No silent default: a self-consumption archetype must state the cap.
    """
    if explicit is not None:
        return abs(float(explicit))
    if key not in params:
        raise ValueError(
            f"self_consumption needs a mapped limit or house_params[{key!r}]"
        )
    return abs(float(params[key]))


def _self_consumption_power_w(
    setpoints: EssSetpoints,
    *,
    package: ArchetypePackage,
    soc_pct: float,
    surplus_kw: float,
    capacity_kwh: float,
    dt_h: float,
) -> float:
    """Battery power (EHAL sign) that absorbs surplus / covers deficit."""
    params = package.house_params
    charge_cap = _cap_w(setpoints.charge_limit_w, params, "ess_max_charge_w")
    discharge_cap = _cap_w(setpoints.discharge_limit_w, params, "ess_max_discharge_w")
    # Energy headroom this tick (no overshoot past 0 / 100 %).
    room_w = (100.0 - soc_pct) / 100.0 * capacity_kwh / dt_h * 1000.0
    avail_w = soc_pct / 100.0 * capacity_kwh / dt_h * 1000.0
    if surplus_kw >= 0:
        return -min(surplus_kw * 1000.0, charge_cap, room_w)
    return min(-surplus_kw * 1000.0, discharge_cap, avail_w)


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
    wallbox_setpoints: Mapping[str, WallboxSetpoints] | None = None,
) -> PhysicsState:
    """Advance house physics by Δt hours using explicit setpoints.

    ``wallbox_setpoints`` (by wallbox id) drive the wallbox model of archetypes
    with ``house_params.wallboxes``; plug events in ``overlay`` apply first.
    """
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

    load_kw = float(package.house_params.get("load_kw", state.load_kw))
    if overlay is not None and overlay.load_spike_remaining_h > 0:
        load_kw = load_kw + float(overlay.load_spike_extra_kw)

    evcs_power_w, evcs = _step_wallboxes(
        state,
        package=package,
        overlay=overlay,
        wallbox_setpoints=wallbox_setpoints,
        dt_h=dt_h,
    )
    load_kw = load_kw + evcs_power_w / 1000.0

    if setpoints.self_consumption:
        ess_power_w = _self_consumption_power_w(
            setpoints,
            package=package,
            soc_pct=state.soc_pct,
            surplus_kw=pv_kw - load_kw,
            capacity_kwh=capacity_kwh,
            dt_h=dt_h,
        )
    else:
        ess_power_w = resolve_ess_power_w(setpoints)
    ess_kw = ess_power_w / 1000.0
    soc = state.soc_pct - (ess_kw * dt_h / capacity_kwh) * 100.0
    soc = max(0.0, min(100.0, soc))

    # EHAL sign: ess + discharge covers load, − charge adds to it; grid + import.
    grid_kw = load_kw - pv_kw - ess_kw
    grid_power_w = grid_kw * 1000.0

    pv_delta = max(0.0, float(pv_kw)) * float(dt_h)
    import_delta = max(0.0, float(grid_kw)) * float(dt_h)
    export_delta = max(0.0, -float(grid_kw)) * float(dt_h)
    # EHAL sign: + discharge, − charge.
    charge_delta = max(0.0, -ess_kw) * float(dt_h)
    discharge_delta = max(0.0, ess_kw) * float(dt_h)

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
        ess_charge_energy_kwh=state.ess_charge_energy_kwh + charge_delta,
        ess_discharge_energy_kwh=state.ess_discharge_energy_kwh + discharge_delta,
        evcs=evcs,
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
    wallbox_setpoints: Mapping[str, WallboxSetpoints] | None = None,
    read_wallbox_setpoints=None,
) -> PhysicsState:
    """Run n closed-loop ticks; project physics onto the store after each step.

    ``read_setpoints`` if provided is ``callable(store, package) -> EssSetpoints``
    and is called before each tick (mock adapter). Otherwise ``setpoints`` is reused.
    ``read_wallbox_setpoints`` / ``wallbox_setpoints`` work the same way for wallboxes.
    """
    state = physics or initial_physics(package)
    project_physics_to_store(store, package=package, physics=state.as_dict())
    current = setpoints or EssSetpoints()
    current_wallbox = wallbox_setpoints
    for _ in range(int(n_ticks)):
        if read_setpoints is not None:
            current = read_setpoints(store, package)
        if read_wallbox_setpoints is not None:
            current_wallbox = read_wallbox_setpoints(store, package)
        state = step_physics(
            state,
            package=package,
            setpoints=current,
            dt_h=dt_h,
            overlay=overlay,
            wallbox_setpoints=current_wallbox,
        )
        project_physics_to_store(store, package=package, physics=state.as_dict())
    return state
