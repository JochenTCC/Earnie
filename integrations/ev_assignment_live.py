"""Live driver of the dynamic EV ↔ wallbox assignment (multi-EV M3).

Reads the plug sensor of every wallbox open to dynamic EVs and the cars' own plug and
charge power sensors, runs :class:`optimizer.ev_assignment.AssignmentEngine`, writes the test
charge setpoints and installs the assignments as overlay for the planner
(``runtime_store.ev_assignments``).

- :func:`start` at daemon start: the overlay is empty, every dynamic EV is unassigned (D7);
  pick requests left from before the start are dropped.
- :func:`tick` at the start of every cycle; :func:`poll` from the daemon's wait loop every
  ``poll_sec`` (the test charge runs there and never delays a plan). An assignment that
  changes in the wait loop wakes a new plan at once.
- :func:`write_unassigned_wallboxes` after the planned EV writes: every wallbox without an
  assigned car follows its ``unknown_vehicle`` policy (D6); a wallbox in a test charge is left
  to the test.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from optimizer.ev_assignment import (
    DEFAULT_SETTINGS,
    STATUS_ASSIGNED,
    STATUS_TESTING,
    AssignmentEngine,
    AssignmentSettings,
    EvObservation,
    EvSpec,
    Pick,
    StepResult,
    ProbeWrite,
    WallboxSpec,
)

logger = logging.getLogger(__name__)

_engine: AssignmentEngine | None = None
_spec_key: tuple | None = None
_wallboxes: dict[str, dict[str, Any]] = {}
_last_poll: float | None = None
_settings: AssignmentSettings = DEFAULT_SETTINGS


def reset_for_tests(settings: AssignmentSettings = DEFAULT_SETTINGS) -> None:
    global _engine, _spec_key, _wallboxes, _last_poll, _settings
    _engine = None
    _spec_key = None
    _wallboxes = {}
    _last_poll = None
    _settings = settings


def engine() -> AssignmentEngine | None:
    return _engine


def start() -> None:
    """Daemon start: no assignment survives a restart (D7)."""
    from runtime_store.ev_assignments import consume_picks, set_live_assignments

    global _engine, _spec_key
    _engine = None
    _spec_key = None
    set_live_assignments({})
    stale = consume_picks()
    if stale:
        logger.info("EV-Zuordnung: %s Auswahl(en) von vor dem Start verworfen.", len(stale))


# --------------------------------------------------------------------------- setup


def _dynamic_setup() -> tuple[list[dict], dict[str, dict[str, Any]]]:
    """(dynamic EVs in MILP shape without overlay, wallboxes open to them by id)."""
    import config
    from house_config.wallboxes import VIEW_DYNAMIC_KEY, is_dynamic_ev

    evs = [
        c
        for c in config.get_flexible_consumers(raw_dynamic=True)
        if str(c.get("type") or "") == "ev" and is_dynamic_ev(c)
    ]
    wallboxes: dict[str, dict[str, Any]] = {}
    for ev in evs:
        for wallbox in ev.get(VIEW_DYNAMIC_KEY) or []:
            wallboxes.setdefault(wallbox["id"], wallbox)
    return evs, wallboxes


def charger_consumer(wallbox: dict[str, Any]) -> dict[str, Any]:
    """The wallbox as charger entry (``evcs.<Wallbox>.*``), with its voltage / phases."""
    from house_config.wallboxes import (
        VIEW_SCHEDULE_PHASES,
        VIEW_SCHEDULE_VOLTAGE,
        VIEW_WALLBOX_KEY,
    )

    return {
        "id": wallbox["id"],
        "name": wallbox.get("label") or wallbox["id"],
        "type": "ev",
        "ehal_bindings": dict(wallbox.get("ehal_bindings") or {}),
        "charging_schedule": {
            VIEW_SCHEDULE_VOLTAGE: float(wallbox["voltage_v"]),
            VIEW_SCHEDULE_PHASES: int(wallbox["phases"]),
        },
        VIEW_WALLBOX_KEY: dict(wallbox),
    }


def dynamic_charger_consumers() -> list[dict[str, Any]]:
    """Charger entries of every wallbox open to dynamic EVs (live config)."""
    _evs, wallboxes = _dynamic_setup()
    return [charger_consumer(w) for w in wallboxes.values()]


def _specs(
    evs: list[dict], wallboxes: dict[str, dict[str, Any]]
) -> tuple[list[WallboxSpec], list[EvSpec]]:
    from house_config.wallboxes import dynamic_wallbox_ids, pair_limits
    from settings.ehal_marker_resolve import resolve_lox_marker

    ev_specs: list[EvSpec] = []
    test_current: dict[str, float] = {}
    for ev in evs:
        ids = tuple(dynamic_wallbox_ids(ev))
        for wallbox_id in ids:
            low = pair_limits(ev, wallboxes[wallbox_id], label=f"E-Auto '{ev['id']}'")[
                "min_current_a"
            ]
            test_current[wallbox_id] = max(test_current.get(wallbox_id, 0.0), low)
        ev_specs.append(
            EvSpec(
                id=str(ev["id"]),
                wallbox_ids=ids,
                has_plug_sensor=bool(resolve_lox_marker(ev, "sens_ev_connected")),
                has_power_sensor=bool(resolve_lox_marker(ev, "sens_ev_charge_power")),
            )
        )
    wallbox_specs = [
        WallboxSpec(id=wid, test_current_a=test_current[wid]) for wid in sorted(wallboxes)
    ]
    return wallbox_specs, ev_specs


# --------------------------------------------------------------------------- reads


def _read_bool(address: str) -> bool | None:
    from integrations import ehal_live

    if not address:
        return None
    value = ehal_live.read_generic_value(address)
    if value is None:
        return None
    return int(round(float(value))) == 1


def _read_wallbox_plugged(wallbox: dict[str, Any]) -> bool | None:
    from settings.ehal_marker_resolve import resolve_lox_marker

    return _read_bool(resolve_lox_marker(charger_consumer(wallbox), "sens_evcs_connected"))


def _read_ev(ev: dict) -> EvObservation:
    from integrations import ehal_live
    from optimizer.charge_immediate import fetch_charge_immediate_switch
    from settings.ehal_marker_resolve import resolve_lox_marker

    power_address = resolve_lox_marker(ev, "sens_ev_charge_power")
    power = ehal_live.read_generic_value(power_address) if power_address else None
    return EvObservation(
        plugged=_read_bool(resolve_lox_marker(ev, "sens_ev_connected")),
        power_w=float(power) if power is not None else None,
        immediate=fetch_charge_immediate_switch(ev) is True,
    )


def _picks() -> list[Pick]:
    from runtime_store.ev_assignments import consume_picks

    out: list[Pick] = []
    for raw in consume_picks():
        try:
            out.append(Pick(str(raw["wallbox_id"]), str(raw["ev_id"]), str(raw["session"])))
        except KeyError as exc:
            logger.error("EV-Zuordnung: ungültige Auswahl %r (%s fehlt).", raw, exc)
    return out


# --------------------------------------------------------------------------- tick


def tick(now: datetime | None = None, *, wake: bool = False) -> StepResult | None:
    """One engine step; ``None`` when no EV is dynamic (the overlay is then empty)."""
    from runtime_store.ev_assignments import set_live_assignments, write_assignments_snapshot

    global _engine, _spec_key, _wallboxes
    evs, wallboxes = _dynamic_setup()
    if not evs:
        _engine = None
        _spec_key = None
        _wallboxes = {}
        set_live_assignments({})
        return None
    wallbox_specs, ev_specs = _specs(evs, wallboxes)
    key = (tuple(wallbox_specs), tuple(ev_specs))
    if _engine is None or key != _spec_key:
        if _engine is not None and _engine.assignments():
            logger.warning(
                "EV-Zuordnung: Konfiguration geändert — Zuordnungen %s verworfen.",
                _engine.assignments(),
            )
        _engine = AssignmentEngine(wallbox_specs, ev_specs, _settings)
        _spec_key = key
    _wallboxes = wallboxes
    stamp = now or datetime.now(timezone.utc)
    plugged = {wid: _read_wallbox_plugged(w) for wid, w in wallboxes.items()}
    ev_obs = {str(ev["id"]): _read_ev(ev) for ev in evs}
    from runtime_store.shadow.hooks import should_invoke_setpoint_writes

    result = _engine.step(
        stamp, plugged, ev_obs, _picks(), allow_test=should_invoke_setpoint_writes()
    )
    for write in result.writes:
        _write_test(write)
    set_live_assignments(_engine.assignments(), free_wallbox_ids=_engine.free_wallboxes())
    if result.changed:
        write_assignments_snapshot(_engine.snapshot(ev_obs), updated_at=stamp.isoformat())
        for row in _engine.snapshot(ev_obs):
            logger.info(
                "EV-Zuordnung %s: %s%s%s",
                row["wallbox_id"],
                row["status"],
                f" → {row['ev_id']} ({row['evidence']})" if row["ev_id"] else "",
                f" — {row['note']}" if row["note"] else "",
            )
    if wake and result.assignment_changed:
        from integrations.ehal_request_http import signal_optimize_request

        signal_optimize_request()
    return result


def poll(clock_fn=time.monotonic) -> None:
    """Wait-loop tick, at most every ``poll_sec``; errors are logged, the daemon keeps waiting."""
    global _last_poll
    now = clock_fn()
    if _last_poll is not None and now - _last_poll < _settings.poll_sec:
        return
    _last_poll = now
    try:
        tick(wake=True)
    except Exception:  # noqa: BLE001 — the wait loop must survive; logged as error
        logger.exception("EV-Zuordnung: Schritt im Warte-Takt fehlgeschlagen.")


# --------------------------------------------------------------------------- writes


def _charger_adapter():
    from integrations import ehal_live

    if ehal_live.is_ehal_network_backend():
        return ehal_live.get_network_adapter()
    return ehal_live.get_loxone_adapter()


def _write_charger(
    wallbox: dict[str, Any], current_a: float, mode: str
) -> tuple[Any, list[dict[str, Any]]]:
    from ehal.qualified_ids import charger_id_of_ev, qualified_charger_id
    from house_config.wallboxes import wallbox_binding_key
    from ehal import EHAL_SCHEMA_VERSION
    from integrations.ehal_live import persist_write_error
    from integrations.ehal_live_records import (
        _last_skipped,
        _last_unconfigured,
        build_ehal_write_records,
    )

    adapter = _charger_adapter()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    written: dict[str, Any] = {"set_evcs_max_current": float(current_a)}
    if wallbox_binding_key(wallbox, "set_evcs_mode"):
        written["set_evcs_mode"] = mode
    charger_id = charger_id_of_ev(charger_consumer(wallbox))
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        **written,
    }
    error = adapter.write_evcs_setpoints(
        charger_id,
        setpoint,
        voltage_v=float(wallbox["voltage_v"]),
        phases=int(wallbox["phases"]),
    )
    if error is not None:
        persist_write_error(error)
    rows = build_ehal_write_records(
        written,
        written_at=ts,
        error=error,
        skipped=_last_skipped(adapter),
        unconfigured=_last_unconfigured(adapter),
    )
    for row in rows:
        row["field"] = qualified_charger_id(charger_id, row["field"])
    return error, rows


def _write_test(write: ProbeWrite) -> None:
    wallbox = _wallboxes[write.wallbox_id]
    mode = "now" if write.start else "off"
    error, _rows = _write_charger(wallbox, write.current_a, mode)
    logger.info(
        "EV-Zuordnung %s: Probeladung %s (%.1f A)%s",
        write.wallbox_id,
        "Start" if write.start else "Ende",
        write.current_a,
        f" — Fehler: {error.get('message')}" if error else "",
    )


def _policy_setpoint(wallbox: dict[str, Any]) -> tuple[float, str]:
    from house_config.wallboxes import (
        UNKNOWN_VEHICLE_IMMEDIATE,
        UNKNOWN_VEHICLE_KEY,
        UNKNOWN_VEHICLE_OFF,
        UNKNOWN_VEHICLE_PV_ONLY,
    )

    policy = wallbox[UNKNOWN_VEHICLE_KEY]
    if policy == UNKNOWN_VEHICLE_OFF:
        return 0.0, "off"
    if policy == UNKNOWN_VEHICLE_IMMEDIATE:
        return float(wallbox["max_current_a"]), "now"
    if policy == UNKNOWN_VEHICLE_PV_ONLY:
        # The vendor's PV mode regulates the current up to the wallbox's maximum.
        return float(wallbox["max_current_a"]), "pv"
    raise ValueError(f"wallboxes '{wallbox['id']}': unbekannte Richtlinie {policy!r}.")


def write_unassigned_wallboxes() -> tuple[Any, list[dict[str, Any]]]:
    """Policy write for every dynamic wallbox without an assigned car (D6).

    Returns the first write error and the trace rows (``evcs.<Wallbox>.set_evcs_*``).
    """
    if _engine is None:
        return None, []
    first_error = None
    records: list[dict[str, Any]] = []
    for wid, state in sorted(_engine.states.items()):
        if state.status in (STATUS_ASSIGNED, STATUS_TESTING):
            continue
        current_a, mode = _policy_setpoint(_wallboxes[wid])
        error, rows = _write_charger(_wallboxes[wid], current_a, mode)
        first_error = first_error or error
        records.extend(rows)
    return first_error, records


def snapshot() -> list[dict[str, Any]]:
    """Current assignment rows for the cycle record (empty without dynamic EVs)."""
    return _engine.snapshot() if _engine is not None else []
