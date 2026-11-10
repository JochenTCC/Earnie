"""Dynamic EV ↔ wallbox assignment: per-wallbox state machine (multi-EV M3, D4–D7).

Pure logic without I/O; the live driver (``integrations.ev_assignment_live``) reads the
sensors, calls :meth:`AssignmentEngine.step` and carries out the test charge writes.

States per wallbox: ``free`` → ``plugged_unknown`` → (``testing``) → ``assigned`` → ``free``
on unplug. Evidence, in order (D4; the vehicle ID step (a) is not built, Q2):

- **plug match** (b): the wallbox reports a plug edge and, within ``match_window_sec``, exactly
  one candidate car reports its own plug edge, and no other open wallbox could explain that
  car's edge. Decided once the window after the wallbox's edge has passed.
- **test charge** (c, D5): the wallbox gets its test current for at most
  ``test_duration_sec``; positive when exactly one candidate's charge power reaches
  ``test_power_threshold_w``. One wallbox at a time; not while a candidate requests
  "Sofort laden"; only with at least one candidate that has a charge power sensor.
- **user pick** (d): the Monitor page names the car for the current plug session.

Nothing is guessed: without evidence the wallbox stays ``plugged_unknown`` and follows its
``unknown_vehicle`` policy (D6). The engine starts empty; on daemon start every plugged
wallbox begins as ``plugged_unknown`` without a plug edge (D7), so plug match cannot apply
and the ladder continues with the test charge.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

STATUS_FREE = "free"
STATUS_PLUGGED_UNKNOWN = "plugged_unknown"
STATUS_TESTING = "testing"
STATUS_ASSIGNED = "assigned"

EVIDENCE_PLUG_MATCH = "plug_match"
EVIDENCE_TEST_CHARGE = "test_charge"
EVIDENCE_USER_PICK = "user_pick"


@dataclass(frozen=True)
class AssignmentSettings:
    """Timing and threshold of the assignment (documented in ``docs/referenz/ehal.md``)."""

    poll_sec: float = 10.0
    match_window_sec: float = 300.0
    test_duration_sec: float = 120.0
    test_power_threshold_w: float = 500.0


DEFAULT_SETTINGS = AssignmentSettings()


@dataclass(frozen=True)
class WallboxSpec:
    id: str
    # Current of the test charge: the largest pair minimum over the cars that may use it.
    test_current_a: float


@dataclass(frozen=True)
class EvSpec:
    id: str
    wallbox_ids: tuple[str, ...]
    has_plug_sensor: bool
    has_power_sensor: bool


@dataclass(frozen=True)
class EvObservation:
    plugged: bool | None = None
    power_w: float | None = None
    immediate: bool = False


@dataclass(frozen=True)
class Pick:
    """User pick from the Monitor page for one plug session of one wallbox."""

    wallbox_id: str
    ev_id: str
    session: str


@dataclass(frozen=True)
class ProbeWrite:
    """Setpoint the driver writes for a test charge: start (current > 0) or stop (0 A)."""

    wallbox_id: str
    current_a: float

    @property
    def start(self) -> bool:
        return self.current_a > 0.0


@dataclass
class WallboxState:
    status: str = STATUS_FREE
    ev_id: str | None = None
    evidence: str | None = None
    since: datetime | None = None
    # Plug session: set when the wallbox becomes plugged; a pick names it.
    session: str | None = None
    # Wallbox plug edge seen by the engine (None after a restart: plugged before start).
    plugged_at: datetime | None = None
    match_decided: bool = False
    test_done: bool = False
    test_started: datetime | None = None
    test_candidates: tuple[str, ...] = ()
    note: str = ""


@dataclass
class StepResult:
    changed: bool = False
    assignment_changed: bool = False
    writes: list[ProbeWrite] = field(default_factory=list)


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts is not None else None


class AssignmentEngine:
    def __init__(
        self,
        wallboxes: list[WallboxSpec],
        evs: list[EvSpec],
        settings: AssignmentSettings = DEFAULT_SETTINGS,
    ) -> None:
        self.settings = settings
        self.wallboxes = {w.id: w for w in wallboxes}
        self.evs = {e.id: e for e in evs}
        for ev in evs:
            unknown = [w for w in ev.wallbox_ids if w not in self.wallboxes]
            if unknown:
                raise ValueError(f"E-Auto '{ev.id}': unbekannte Wallbox(en) {unknown}.")
        self.states: dict[str, WallboxState] = {w.id: WallboxState() for w in wallboxes}
        self._wallbox_plug: dict[str, bool | None] = {}
        self._ev_plug: dict[str, bool | None] = {}
        self._ev_edge: dict[str, datetime] = {}

    # ------------------------------------------------------------------ queries

    def assignments(self) -> dict[str, str]:
        """EV id → wallbox id of every assigned wallbox."""
        return {
            s.ev_id: wid
            for wid, s in self.states.items()
            if s.status == STATUS_ASSIGNED and s.ev_id
        }

    def free_wallboxes(self) -> list[str]:
        """Wallboxes in state ``free`` (the pool of the EVs that are not assigned, M4 / D8)."""
        return sorted(wid for wid, s in self.states.items() if s.status == STATUS_FREE)

    def candidates(self, wallbox_id: str, ev_obs: dict[str, EvObservation]) -> list[str]:
        """Cars that may be at ``wallbox_id``: allowed there, not assigned elsewhere, and not
        reporting "not plugged" through their own plug sensor."""
        taken = {ev: wid for ev, wid in self.assignments().items() if wid != wallbox_id}
        out: list[str] = []
        for ev in self.evs.values():
            if wallbox_id not in ev.wallbox_ids or ev.id in taken:
                continue
            obs = ev_obs.get(ev.id) or EvObservation()
            if ev.has_plug_sensor and obs.plugged is False:
                continue
            out.append(ev.id)
        return sorted(out)

    def snapshot(self, ev_obs: dict[str, EvObservation] | None = None) -> list[dict[str, Any]]:
        obs = ev_obs or {}
        rows: list[dict[str, Any]] = []
        for wid in sorted(self.states):
            s = self.states[wid]
            rows.append(
                {
                    "wallbox_id": wid,
                    "status": s.status,
                    "ev_id": s.ev_id,
                    "evidence": s.evidence,
                    "since": _iso(s.since),
                    "session": s.session,
                    "note": s.note,
                    "candidates": (
                        self.candidates(wid, obs) if s.status != STATUS_FREE else []
                    ),
                }
            )
        return rows

    # ------------------------------------------------------------------ step

    def step(
        self,
        now: datetime,
        wallbox_plugged: dict[str, bool | None],
        ev_obs: dict[str, EvObservation],
        picks: list[Pick] | None = None,
        *,
        allow_test: bool = True,
    ) -> StepResult:
        """One step. ``allow_test=False`` (setpoints are not written, e.g. silent mode)
        starts no test charge; the wallbox waits for the user's pick."""
        before = {wid: replace(s) for wid, s in self.states.items()}
        before_assign = self.assignments()
        result = StepResult()
        self._track_ev_edges(now, ev_obs)
        for wid in sorted(self.states):
            self._track_wallbox(now, wid, wallbox_plugged.get(wid), result)
        for pick in picks or []:
            self._apply_pick(now, pick, ev_obs, result)
        for wid in sorted(self.states):
            if self.states[wid].status == STATUS_TESTING:
                self._evaluate_test(now, wid, ev_obs, result)
        for wid in sorted(self.states):
            if self.states[wid].status == STATUS_PLUGGED_UNKNOWN:
                self._try_plug_match(now, wid, ev_obs)
        for wid in sorted(self.states):
            if self.states[wid].status == STATUS_PLUGGED_UNKNOWN:
                if allow_test:
                    self._try_start_test(now, wid, ev_obs, result)
                elif self.states[wid].match_decided or self.states[wid].plugged_at is None:
                    self.states[wid].note = "Probeladung nicht möglich (Sollwerte werden nicht gesendet)"
        result.assignment_changed = self.assignments() != before_assign
        result.changed = result.assignment_changed or any(
            before[wid] != self.states[wid] for wid in self.states
        )
        return result

    def _track_ev_edges(self, now: datetime, ev_obs: dict[str, EvObservation]) -> None:
        for ev in self.evs.values():
            if not ev.has_plug_sensor:
                continue
            plugged = (ev_obs.get(ev.id) or EvObservation()).plugged
            if plugged is None:
                continue
            seen = ev.id in self._ev_plug
            previous = self._ev_plug.get(ev.id)
            self._ev_plug[ev.id] = plugged
            if not plugged:
                self._ev_edge.pop(ev.id, None)
            elif seen and previous is False:
                self._ev_edge[ev.id] = now

    def _track_wallbox(
        self, now: datetime, wid: str, plugged: bool | None, result: StepResult
    ) -> None:
        state = self.states[wid]
        if plugged is None:
            if state.status != STATUS_FREE:
                state.note = "Stecker-Sensor der Wallbox ohne Wert"
            return
        seen = wid in self._wallbox_plug
        previous = self._wallbox_plug.get(wid)
        self._wallbox_plug[wid] = plugged
        if not plugged:
            if state.status == STATUS_TESTING:
                result.writes.append(ProbeWrite(wid, 0.0))
            if state.status != STATUS_FREE:
                self.states[wid] = WallboxState(since=now)
            return
        if state.status == STATUS_FREE:
            edge = seen and previous is False
            self.states[wid] = WallboxState(
                status=STATUS_PLUGGED_UNKNOWN,
                since=now,
                session=now.isoformat(),
                plugged_at=now if edge else None,
                note="" if edge else "beim Start schon angesteckt",
            )

    def _assign(self, now: datetime, wid: str, ev_id: str, evidence: str) -> None:
        state = self.states[wid]
        state.status = STATUS_ASSIGNED
        state.ev_id = ev_id
        state.evidence = evidence
        state.since = now
        state.test_started = None
        state.test_candidates = ()
        state.note = ""

    def _apply_pick(
        self,
        now: datetime,
        pick: Pick,
        ev_obs: dict[str, EvObservation],
        result: StepResult,
    ) -> None:
        state = self.states.get(pick.wallbox_id)
        ev = self.evs.get(pick.ev_id)
        if state is None or ev is None or pick.wallbox_id not in ev.wallbox_ids:
            return
        if state.status == STATUS_FREE or state.session != pick.session:
            return
        other = self.assignments().get(pick.ev_id)
        if other is not None and other != pick.wallbox_id:
            # The user's pick wins; the other wallbox does not know its car any more.
            moved = self.states[other]
            moved.status = STATUS_PLUGGED_UNKNOWN
            moved.ev_id = None
            moved.evidence = None
            moved.since = now
            moved.match_decided = True
            moved.test_done = True
            moved.note = f"Auswahl: '{pick.ev_id}' steht an Wallbox '{pick.wallbox_id}'"
        if state.status == STATUS_TESTING:
            result.writes.append(ProbeWrite(pick.wallbox_id, 0.0))
        self._assign(now, pick.wallbox_id, pick.ev_id, EVIDENCE_USER_PICK)

    def _try_plug_match(
        self, now: datetime, wid: str, ev_obs: dict[str, EvObservation]
    ) -> None:
        state = self.states[wid]
        if state.match_decided or state.plugged_at is None:
            return
        window = timedelta(seconds=self.settings.match_window_sec)
        if now < state.plugged_at + window:
            state.note = "wartet auf Steckabgleich"
            return
        state.match_decided = True
        edged = [
            ev_id
            for ev_id in self.candidates(wid, ev_obs)
            if ev_id in self._ev_edge and abs(self._ev_edge[ev_id] - state.plugged_at) <= window
        ]
        if len(edged) != 1:
            state.note = (
                "kein Auto meldete sich beim Anstecken"
                if not edged
                else "mehrere Autos meldeten sich beim Anstecken"
            )
            return
        ev_id = edged[0]
        edge = self._ev_edge[ev_id]
        for other_id, other in self.states.items():
            if other_id == wid or other.status not in (STATUS_PLUGGED_UNKNOWN, STATUS_TESTING):
                continue
            if other_id not in self.evs[ev_id].wallbox_ids:
                continue
            if other.plugged_at is None or abs(edge - other.plugged_at) <= window:
                state.note = f"Wallbox '{other_id}' wurde zur selben Zeit angesteckt"
                return
        self._assign(now, wid, ev_id, EVIDENCE_PLUG_MATCH)

    def _try_start_test(
        self,
        now: datetime,
        wid: str,
        ev_obs: dict[str, EvObservation],
        result: StepResult,
    ) -> None:
        state = self.states[wid]
        if state.test_done or (state.plugged_at is not None and not state.match_decided):
            return
        candidates = self.candidates(wid, ev_obs)
        if not candidates:
            state.note = "kein dynamisches E-Auto kommt in Frage"
            return
        if not any(self.evs[c].has_power_sensor for c in candidates):
            state.test_done = True
            state.note = "Probeladung nicht möglich (kein Auto mit Ladeleistungs-Sensor)"
            return
        if any((ev_obs.get(c) or EvObservation()).immediate for c in candidates):
            state.note = "Probeladung ausgesetzt (Sofort laden)"
            return
        if any(s.status == STATUS_TESTING for s in self.states.values()):
            state.note = "Probeladung wartet auf eine andere Wallbox"
            return
        state.status = STATUS_TESTING
        state.test_started = now
        state.test_candidates = tuple(candidates)
        state.note = ""
        result.writes.append(ProbeWrite(wid, self.wallboxes[wid].test_current_a))

    def _evaluate_test(
        self,
        now: datetime,
        wid: str,
        ev_obs: dict[str, EvObservation],
        result: StepResult,
    ) -> None:
        state = self.states[wid]
        candidates = state.test_candidates
        if any((ev_obs.get(c) or EvObservation()).immediate for c in candidates):
            result.writes.append(ProbeWrite(wid, 0.0))
            state.status = STATUS_PLUGGED_UNKNOWN
            state.test_started = None
            state.note = "Probeladung abgebrochen (Sofort laden)"
            return
        threshold = self.settings.test_power_threshold_w
        reacting = [
            c
            for c in candidates
            if (power := (ev_obs.get(c) or EvObservation()).power_w) is not None
            and power >= threshold
        ]
        if len(reacting) == 1:
            result.writes.append(ProbeWrite(wid, 0.0))
            self._assign(now, wid, reacting[0], EVIDENCE_TEST_CHARGE)
            return
        timed_out = state.test_started is not None and now >= state.test_started + timedelta(
            seconds=self.settings.test_duration_sec
        )
        if len(reacting) > 1 or timed_out:
            result.writes.append(ProbeWrite(wid, 0.0))
            state.status = STATUS_PLUGGED_UNKNOWN
            state.test_started = None
            state.test_done = True
            state.note = (
                "Probeladung mehrdeutig: mehrere Autos luden"
                if len(reacting) > 1
                else "Probeladung: kein Auto hat reagiert"
            )
