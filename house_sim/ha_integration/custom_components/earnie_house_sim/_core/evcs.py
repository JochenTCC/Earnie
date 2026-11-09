# GENERATED — edit house_sim/core/ (or fixtures), then run:
#   python -m scripts.sync_house_sim_integration
# Do not hand-edit this copy.
"""Wallbox and EV physics (HouseSim wallbox write-back, W1).

Limits are currents on both devices (decision D2 of
``docs/dev/multi-ev-wallbox-plan.md``). For a pair, the minimum current is the
larger of the two minimums, the maximum current the smaller of the two
maximums, the phases the smaller count. A wallbox charges the EV plugged into
it with ``I × U × phases``, where ``I`` is the wallbox setpoint capped at the
pair's maximum (0 below the pair's minimum); the energy left to 100 % caps the
result. The EV's SoC counts the AC energy charged (no charge losses here).

Parameters come from ``house_params``::

    "wallboxes": [{"id": "lp1", "voltage_v": 230, "phases": 3,
                   "min_current_a": 6, "max_current_a": 16,
                   "read_only": false, "initial_ev_id": "car_a"}],
    "evs": [{"id": "car_a", "capacity_kwh": 60, "initial_soc_pct": 40,
             "min_current_a": 6, "max_current_a": 16, "phases": 3,
             "vehicle_id": "Car A"}]

``read_only`` (optional, default ``false``) marks a wallbox that takes no
setpoints (e.g. KEBA without write access): it charges at the pair's maximum.
``initial_ev_id`` and ``vehicle_id`` are optional.

Optional ``entities`` connect the model to vendor entities (W2)::

    wallbox "entities": {
      "max_current": "number.evcc_loadpoint_1_max_current",      # setpoint, A
      "enable": {"entity_id": "switch.evcc_loadpoint_1_enable",  # charges unless
                 "off_states": ["off"]},                         # in an off state
      "power": "sensor.evcc_loadpoint_1_charge_power",
      "energy": "sensor.keba_p30_total_energy",                  # counter
      "plugged": "binary_sensor.evcc_loadpoint_1_connected",     # on / off
      "status": {"entity_id": "sensor.goe_x_car",                # vendor states
                 "states": {"none": "1", "charging": "2",
                            "connected": "3", "complete": "4"}},
      "vehicle": "sensor.evcc_loadpoint_1_vehicle_name"}         # vehicle_id or ""
    EV "entities": {"soc": ..., "plugged": ..., "power": ...}

No Earnie imports: this module is copied into the S4 HA integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping


# Car status of a wallbox, mapped onto vendor states by ``entities.status``.
STATUS_NONE = "none"  # no car plugged in
STATUS_CONNECTED = "connected"  # car plugged in, not charging, not full
STATUS_CHARGING = "charging"
STATUS_COMPLETE = "complete"  # car plugged in and full
STATUS_KEYS = (STATUS_NONE, STATUS_CONNECTED, STATUS_CHARGING, STATUS_COMPLETE)

PLUGGED_ON = "on"
PLUGGED_OFF = "off"


@dataclass(frozen=True)
class WallboxEntities:
    """Vendor entities of one wallbox (all optional; see module docstring)."""

    max_current: str | None = None
    enable: str | None = None
    enable_off_states: tuple[str, ...] = ()
    power: str | None = None
    energy: str | None = None
    plugged: str | None = None
    status: str | None = None
    status_states: Mapping[str, str] = field(default_factory=dict)
    vehicle: str | None = None


@dataclass(frozen=True)
class EvEntities:
    """Vehicle-side entities of one EV (all optional)."""

    soc: str | None = None
    plugged: str | None = None
    power: str | None = None


@dataclass(frozen=True)
class WallboxParams:
    id: str
    voltage_v: float
    phases: int
    min_current_a: float
    max_current_a: float
    read_only: bool = False
    initial_ev_id: str | None = None
    entities: WallboxEntities = field(default_factory=WallboxEntities)


@dataclass(frozen=True)
class EvParams:
    id: str
    capacity_kwh: float
    initial_soc_pct: float
    min_current_a: float
    max_current_a: float
    phases: int
    vehicle_id: str | None = None
    entities: EvEntities = field(default_factory=EvEntities)


@dataclass(frozen=True)
class WallboxSetpoints:
    """Setpoints of one wallbox for one tick.

    ``enabled``: the vendor's enable / force-on state. A wallbox without such an
    entity has no way to be switched off, so its setpoints carry ``True``.
    """

    max_current_a: float
    enabled: bool = True


@dataclass(frozen=True)
class EvcsState:
    """Plug connections, EV SoC and the power of each wallbox in the last tick."""

    ev_at_wallbox: Mapping[str, str] = field(default_factory=dict)
    ev_soc_pct: Mapping[str, float] = field(default_factory=dict)
    wallbox_power_w: Mapping[str, float] = field(default_factory=dict)
    wallbox_energy_kwh: Mapping[str, float] = field(default_factory=dict)

    @property
    def total_power_w(self) -> float:
        return float(sum(self.wallbox_power_w.values()))

    def wallbox_of_ev(self, ev_id: str) -> str | None:
        for wallbox_id, connected in self.ev_at_wallbox.items():
            if connected == ev_id:
                return wallbox_id
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ev_at_wallbox": dict(self.ev_at_wallbox),
            "ev_soc_pct": dict(self.ev_soc_pct),
            "wallbox_power_w": dict(self.wallbox_power_w),
            "wallbox_energy_kwh": dict(self.wallbox_energy_kwh),
        }


@dataclass(frozen=True)
class EvcsEvent:
    """Plug event from a scenario: ``ev_id`` set = plug in, ``None`` = unplug."""

    wallbox_id: str
    ev_id: str | None = None
    soc_pct: float | None = None


def _require(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw or raw[key] is None:
        raise ValueError(f"{where}: missing {key!r}")
    return raw[key]


def _phases(value: Any, where: str) -> int:
    phases = int(value)
    if phases not in (1, 2, 3):
        raise ValueError(f"{where}: phases must be 1, 2 or 3, got {value!r}")
    return phases


def _current_range(raw: Mapping[str, Any], where: str) -> tuple[float, float]:
    min_a = float(_require(raw, "min_current_a", where))
    max_a = float(_require(raw, "max_current_a", where))
    if min_a < 0 or max_a < min_a:
        raise ValueError(f"{where}: need 0 <= min_current_a <= max_current_a")
    return min_a, max_a


def _id(raw: Mapping[str, Any], where: str) -> str:
    value = str(_require(raw, "id", where)).strip()
    if not value:
        raise ValueError(f"{where}: empty 'id'")
    return value


def parse_wallboxes(house_params: Mapping[str, Any]) -> tuple[WallboxParams, ...]:
    raw_list = house_params.get("wallboxes")
    if raw_list is None:
        return ()
    if not isinstance(raw_list, list):
        raise ValueError("house_params.wallboxes must be a list")
    out: list[WallboxParams] = []
    for index, raw in enumerate(raw_list):
        where = f"house_params.wallboxes[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object")
        wid = _id(raw, where)
        voltage = float(_require(raw, "voltage_v", where))
        if voltage <= 0:
            raise ValueError(f"{where}: voltage_v must be > 0")
        min_a, max_a = _current_range(raw, where)
        initial = raw.get("initial_ev_id")
        read_only = bool(raw.get("read_only", False))
        entities = _parse_wallbox_entities(raw.get("entities"), f"{where}.entities")
        if read_only and (entities.max_current or entities.enable):
            raise ValueError(f"{where}: a read_only wallbox takes no setpoint entities")
        out.append(
            WallboxParams(
                id=wid,
                voltage_v=voltage,
                phases=_phases(_require(raw, "phases", where), where),
                min_current_a=min_a,
                max_current_a=max_a,
                read_only=read_only,
                initial_ev_id=str(initial).strip() if initial else None,
                entities=entities,
            )
        )
    _check_unique([w.id for w in out], "wallbox")
    return tuple(out)


def parse_evs(house_params: Mapping[str, Any]) -> tuple[EvParams, ...]:
    raw_list = house_params.get("evs")
    if raw_list is None:
        return ()
    if not isinstance(raw_list, list):
        raise ValueError("house_params.evs must be a list")
    out: list[EvParams] = []
    for index, raw in enumerate(raw_list):
        where = f"house_params.evs[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object")
        capacity = float(_require(raw, "capacity_kwh", where))
        soc = float(_require(raw, "initial_soc_pct", where))
        if capacity <= 0:
            raise ValueError(f"{where}: capacity_kwh must be > 0")
        if not 0.0 <= soc <= 100.0:
            raise ValueError(f"{where}: initial_soc_pct must be within 0..100")
        min_a, max_a = _current_range(raw, where)
        vehicle = raw.get("vehicle_id")
        out.append(
            EvParams(
                id=_id(raw, where),
                capacity_kwh=capacity,
                initial_soc_pct=soc,
                min_current_a=min_a,
                max_current_a=max_a,
                phases=_phases(_require(raw, "phases", where), where),
                vehicle_id=str(vehicle).strip() if vehicle else None,
                entities=_parse_ev_entities(raw.get("entities"), f"{where}.entities"),
            )
        )
    _check_unique([e.id for e in out], "EV")
    return tuple(out)


def _entity_id(value: Any, where: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if "." not in text:
        raise ValueError(f"{where}: {value!r} is no entity id")
    return text


def _parse_wallbox_entities(raw: Any, where: str) -> WallboxEntities:
    """``entities`` of a wallbox.

    ``enable`` is ``{"entity_id": ..., "off_states": [...]}``: the wallbox charges
    unless the entity is in one of the off states (evcc switch: ``["off"]``;
    go-e ``frc``: ``["1"]``). ``status`` is ``{"entity_id": ..., "states":
    {"none": ..., "connected": ..., "charging": ..., "complete": ...}}``.
    """
    if raw is None:
        return WallboxEntities()
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be an object")
    known = {"max_current", "enable", "power", "energy", "plugged", "status", "vehicle"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    enable_id: str | None = None
    off_states: tuple[str, ...] = ()
    if raw.get("enable") is not None:
        enable = raw["enable"]
        if not isinstance(enable, dict):
            raise ValueError(f"{where}.enable must be {{entity_id, off_states}}")
        enable_id = _entity_id(_require(enable, "entity_id", f"{where}.enable"), where)
        states = _require(enable, "off_states", f"{where}.enable")
        if not isinstance(states, list) or not states:
            raise ValueError(f"{where}.enable.off_states must be a non-empty list")
        off_states = tuple(str(s) for s in states)
    status_id: str | None = None
    status_states: dict[str, str] = {}
    if raw.get("status") is not None:
        status = raw["status"]
        if not isinstance(status, dict):
            raise ValueError(f"{where}.status must be {{entity_id, states}}")
        status_id = _entity_id(_require(status, "entity_id", f"{where}.status"), where)
        states = _require(status, "states", f"{where}.status")
        if not isinstance(states, dict) or set(states) != set(STATUS_KEYS):
            raise ValueError(f"{where}.status.states needs exactly {list(STATUS_KEYS)}")
        status_states = {key: str(value) for key, value in states.items()}
    return WallboxEntities(
        max_current=_entity_id(raw.get("max_current"), where),
        enable=enable_id,
        enable_off_states=off_states,
        power=_entity_id(raw.get("power"), where),
        energy=_entity_id(raw.get("energy"), where),
        plugged=_entity_id(raw.get("plugged"), where),
        status=status_id,
        status_states=status_states,
        vehicle=_entity_id(raw.get("vehicle"), where),
    )


def _parse_ev_entities(raw: Any, where: str) -> EvEntities:
    if raw is None:
        return EvEntities()
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(raw) - {"soc", "plugged", "power"}
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    return EvEntities(
        soc=_entity_id(raw.get("soc"), where),
        plugged=_entity_id(raw.get("plugged"), where),
        power=_entity_id(raw.get("power"), where),
    )


def _check_unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for item in ids:
        if item in seen:
            raise ValueError(f"Duplicate {what} id {item!r} in house_params")
        seen.add(item)


def has_wallbox_model(house_params: Mapping[str, Any]) -> bool:
    return house_params.get("wallboxes") is not None


def initial_evcs_state(
    wallboxes: tuple[WallboxParams, ...],
    evs: tuple[EvParams, ...],
    *,
    initial_energy_kwh: Mapping[str, float] | None = None,
) -> EvcsState:
    if wallboxes and not evs:
        raise ValueError("house_params.wallboxes needs house_params.evs")
    ev_ids = {ev.id for ev in evs}
    connected: dict[str, str] = {}
    for wallbox in wallboxes:
        if wallbox.initial_ev_id is None:
            continue
        if wallbox.initial_ev_id not in ev_ids:
            raise ValueError(
                f"Wallbox {wallbox.id!r}: initial_ev_id {wallbox.initial_ev_id!r} is no EV"
            )
        if wallbox.initial_ev_id in connected.values():
            raise ValueError(f"EV {wallbox.initial_ev_id!r} is plugged into two wallboxes")
        connected[wallbox.id] = wallbox.initial_ev_id
    return EvcsState(
        ev_at_wallbox=connected,
        ev_soc_pct={ev.id: ev.initial_soc_pct for ev in evs},
        wallbox_power_w={w.id: 0.0 for w in wallboxes},
        wallbox_energy_kwh={
            w.id: float((initial_energy_kwh or {}).get(w.id, 0.0)) for w in wallboxes
        },
    )


def evcs_state_from_dict(
    raw: Mapping[str, Any],
    *,
    wallboxes: tuple[WallboxParams, ...],
    evs: tuple[EvParams, ...],
) -> EvcsState:
    """Restore a saved :meth:`EvcsState.as_dict`; ids must match the archetype."""
    wallbox_ids = {w.id for w in wallboxes}
    ev_ids = {e.id for e in evs}
    connected = {str(k): str(v) for k, v in dict(raw.get("ev_at_wallbox") or {}).items()}
    soc = {str(k): float(v) for k, v in dict(raw.get("ev_soc_pct") or {}).items()}
    energy = {str(k): float(v) for k, v in dict(raw.get("wallbox_energy_kwh") or {}).items()}
    if not set(connected) <= wallbox_ids or not set(connected.values()) <= ev_ids:
        raise ValueError("Saved wallbox connections do not match the archetype")
    if set(soc) != ev_ids or not set(energy) <= wallbox_ids:
        raise ValueError("Saved EV / wallbox state does not match the archetype")
    if len(set(connected.values())) != len(connected):
        raise ValueError("Saved state has one EV plugged into two wallboxes")
    return EvcsState(
        ev_at_wallbox=connected,
        ev_soc_pct=soc,
        wallbox_power_w={w.id: 0.0 for w in wallboxes},
        wallbox_energy_kwh={w.id: energy.get(w.id, 0.0) for w in wallboxes},
    )


def wallbox_setpoints_from_lookup(
    wallboxes: tuple[WallboxParams, ...],
    *,
    numeric: Callable[[str], float | None],
    text: Callable[[str], str | None],
) -> dict[str, WallboxSetpoints]:
    """Setpoints from the vendor entities: current in A, enable by off states.

    A writable wallbox without a ``max_current`` entity, or whose entity has no
    value, gets no setpoints; charging a car there then raises in the step.
    """
    out: dict[str, WallboxSetpoints] = {}
    for wallbox in wallboxes:
        ents = wallbox.entities
        if wallbox.read_only or not ents.max_current:
            continue
        current = numeric(ents.max_current)
        if current is None:
            continue
        enabled = True
        if ents.enable:
            state = text(ents.enable)
            if state is None:
                raise ValueError(
                    f"Wallbox {wallbox.id!r}: enable entity {ents.enable} has no state"
                )
            enabled = str(state) not in ents.enable_off_states
        out[wallbox.id] = WallboxSetpoints(max_current_a=float(current), enabled=enabled)
    return out


def wallbox_status(state: EvcsState, wallbox_id: str, evs: tuple[EvParams, ...]) -> str:
    ev_id = state.ev_at_wallbox.get(wallbox_id)
    if ev_id is None:
        return STATUS_NONE
    if float(state.wallbox_power_w.get(wallbox_id, 0.0)) > 0.0:
        return STATUS_CHARGING
    if float(state.ev_soc_pct.get(ev_id, 0.0)) >= 100.0:
        return STATUS_COMPLETE
    return STATUS_CONNECTED


def evcs_telemetry(
    state: EvcsState,
    *,
    wallboxes: tuple[WallboxParams, ...],
    evs: tuple[EvParams, ...],
) -> list[tuple[str, str, float | str]]:
    """``(entity_id, quantity, value)`` for every mapped wallbox / EV entity.

    ``quantity`` is ``power`` (W), ``energy`` (kWh), ``percent`` or ``text``
    (written as is: plug ``on`` / ``off``, vendor status, vehicle name or ``""``).
    """
    evs_by_id = {ev.id: ev for ev in evs}
    out: list[tuple[str, str, float | str]] = []
    for wallbox in wallboxes:
        ents = wallbox.entities
        ev_id = state.ev_at_wallbox.get(wallbox.id)
        power_w = float(state.wallbox_power_w.get(wallbox.id, 0.0))
        if ents.power:
            out.append((ents.power, "power", power_w))
        if ents.energy:
            out.append((ents.energy, "energy", float(state.wallbox_energy_kwh.get(wallbox.id, 0.0))))
        if ents.plugged:
            out.append((ents.plugged, "text", PLUGGED_ON if ev_id else PLUGGED_OFF))
        if ents.status:
            status = wallbox_status(state, wallbox.id, evs)
            out.append((ents.status, "text", ents.status_states[status]))
        if ents.vehicle:
            vehicle = evs_by_id[ev_id].vehicle_id if ev_id else None
            out.append((ents.vehicle, "text", vehicle or ""))
    for ev in evs:
        ents = ev.entities
        wallbox_id = state.wallbox_of_ev(ev.id)
        if ents.soc:
            out.append((ents.soc, "percent", float(state.ev_soc_pct.get(ev.id, ev.initial_soc_pct))))
        if ents.plugged:
            out.append((ents.plugged, "text", PLUGGED_ON if wallbox_id else PLUGGED_OFF))
        if ents.power:
            power = state.wallbox_power_w.get(wallbox_id, 0.0) if wallbox_id else 0.0
            out.append((ents.power, "power", float(power)))
    return out


def apply_events(
    state: EvcsState,
    events: list[EvcsEvent],
    *,
    wallboxes: tuple[WallboxParams, ...],
    evs: tuple[EvParams, ...],
) -> EvcsState:
    """Apply plug / unplug events in order. Unknown ids and double plugs raise."""
    wallbox_ids = {w.id for w in wallboxes}
    ev_ids = {e.id for e in evs}
    connected = dict(state.ev_at_wallbox)
    soc = dict(state.ev_soc_pct)
    for event in events:
        if event.wallbox_id not in wallbox_ids:
            raise ValueError(f"Unknown wallbox {event.wallbox_id!r}")
        if event.ev_id is None:
            connected.pop(event.wallbox_id, None)
            continue
        if event.ev_id not in ev_ids:
            raise ValueError(f"Unknown EV {event.ev_id!r}")
        occupant = connected.get(event.wallbox_id)
        if occupant is not None and occupant != event.ev_id:
            raise ValueError(
                f"Wallbox {event.wallbox_id!r} already has EV {occupant!r} plugged in"
            )
        for other_wallbox, other_ev in connected.items():
            if other_ev == event.ev_id and other_wallbox != event.wallbox_id:
                raise ValueError(
                    f"EV {event.ev_id!r} is already plugged into {other_wallbox!r}"
                )
        connected[event.wallbox_id] = event.ev_id
        if event.soc_pct is not None:
            value = float(event.soc_pct)
            if not 0.0 <= value <= 100.0:
                raise ValueError("soc_pct must be within 0..100")
            soc[event.ev_id] = value
    return replace(state, ev_at_wallbox=connected, ev_soc_pct=soc)


def pair_current_range(wallbox: WallboxParams, ev: EvParams) -> tuple[float, float]:
    """Current range (A) of a wallbox–EV pair; raises when the ranges do not overlap."""
    min_a = max(wallbox.min_current_a, ev.min_current_a)
    max_a = min(wallbox.max_current_a, ev.max_current_a)
    if min_a > max_a:
        raise ValueError(
            f"Wallbox {wallbox.id!r} ({wallbox.min_current_a:g}–{wallbox.max_current_a:g} A) "
            f"and EV {ev.id!r} ({ev.min_current_a:g}–{ev.max_current_a:g} A) "
            "have no common charge current"
        )
    return min_a, max_a


def charge_power_w(
    wallbox: WallboxParams,
    ev: EvParams,
    *,
    soc_pct: float,
    setpoints: WallboxSetpoints | None,
    dt_h: float,
) -> float:
    """AC charge power (W) of ``wallbox`` into ``ev`` for one tick of ``dt_h`` hours."""
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    min_a, max_a = pair_current_range(wallbox, ev)
    phases = min(wallbox.phases, ev.phases)
    if wallbox.read_only:
        current_a = max_a
    else:
        if setpoints is None:
            raise ValueError(
                f"Wallbox {wallbox.id!r} has EV {ev.id!r} plugged in but no setpoints"
            )
        if not setpoints.enabled:
            return 0.0
        current_a = min(max(0.0, float(setpoints.max_current_a)), max_a)
        if current_a < min_a or current_a <= 0.0:
            return 0.0
    power_w = current_a * wallbox.voltage_v * phases
    room_kwh = max(0.0, (100.0 - float(soc_pct)) / 100.0 * ev.capacity_kwh)
    return max(0.0, min(power_w, room_kwh / dt_h * 1000.0))


def step_evcs(
    state: EvcsState,
    *,
    wallboxes: tuple[WallboxParams, ...],
    evs: tuple[EvParams, ...],
    setpoints: Mapping[str, WallboxSetpoints] | None,
    dt_h: float,
) -> EvcsState:
    """Charge every plugged-in EV for one tick; returns powers and new SoCs."""
    evs_by_id = {ev.id: ev for ev in evs}
    soc = dict(state.ev_soc_pct)
    powers: dict[str, float] = {}
    for wallbox in wallboxes:
        ev_id = state.ev_at_wallbox.get(wallbox.id)
        if ev_id is None:
            powers[wallbox.id] = 0.0
            continue
        ev = evs_by_id[ev_id]
        power_w = charge_power_w(
            wallbox,
            ev,
            soc_pct=soc[ev_id],
            setpoints=(setpoints or {}).get(wallbox.id),
            dt_h=dt_h,
        )
        powers[wallbox.id] = power_w
        soc[ev_id] = min(100.0, soc[ev_id] + power_w / 1000.0 * dt_h / ev.capacity_kwh * 100.0)
    energy = {
        w.id: float(state.wallbox_energy_kwh.get(w.id, 0.0)) + powers[w.id] / 1000.0 * dt_h
        for w in wallboxes
    }
    return replace(
        state, ev_soc_pct=soc, wallbox_power_w=powers, wallbox_energy_kwh=energy
    )
