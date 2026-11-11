"""Savings ledger: shadow plant slot engine and SA-day close (spec ``docs/dev/savings-ledger.md`` § 3, § 4).

Pure functions, no file I/O and no config reads (files: ``runtime_store.savings_ledger_store``).
One closed quarter-hour slot of the production log is compared with a shadow plant
that has the same house load, PV and prices, and a battery in vendor mode
(``optimizer.battery.vendor_mode_step``, the same step as the "Baseline" simulation)
on its own continuous SoC chain. ``advance`` books the slots into sunrise-to-sunrise
days and returns one ledger row per closed day.

Sign conventions: ``closed_interval`` stores ``battery_kw`` positive while
discharging (``house = pv + grid + battery``) and ``grid_kw`` positive while
importing. The vendor-mode step returns battery power positive while charging.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable

from data.live_consumption import is_dead_telemetry_snapshot
from optimizer import battery as bat
from optimizer.milp_horizon import (
    aggregate_battery_params_for_load,
    coerce_battery_params_list,
)
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from runtime_store.power_interval_sampler import MIN_SAMPLE_COUNT_FOR_MEAN
from runtime_store.savings_ledger_flex import FlexDayInputs, retime_flex_day

SAVINGS_V = 1
# First version with the day replay (flex re-timing, spec § 7); ``SAVINGS_V`` reaches it in Ledger P9d.
SAVINGS_V_REPLAY = 2

# Sources a slot may have per plant channel (spec § 4): energy counters exist for pv and grid only.
_SOURCE_MEAN = "mean"
_SOURCE_COUNTER = "counter"
_MEAN_OR_COUNTER_CHANNELS = ("pv", "grid")
_MEAN_ONLY_CHANNELS = ("battery", "house")
_REQUIRED_POWER_KEYS = ("pv_kw", "grid_kw", "house_kw")

SKIP_MISSING = "missing"
SKIP_FEW_SAMPLES = "few_samples"
SKIP_NOT_MEAN = "not_mean"
SKIP_NO_POWER = "no_power"
SKIP_NO_PRICE = "no_price"
SKIP_DEAD_TELEMETRY = "dead_telemetry"
SKIP_ERROR = "error"
# Slots of the day that were never booked (counted only at the day close, spec § 4).
SKIP_BEFORE_CHAIN = "before_chain"
SKIP_NO_CYCLE = "no_cycle"


@dataclass(frozen=True)
class LedgerSlot:
    """Result of one closed slot. A skipped slot leaves both sides and the shadow SoC unchanged."""

    counted: bool
    skip_reason: str | None
    cost_with_eur: float
    cost_without_eur: float
    shadow_soc_next: float | None
    import_kwh_with: float
    import_kwh_without: float
    export_kwh_with: float
    export_kwh_without: float
    shadow_battery_kw: float

    @property
    def saving_eur(self) -> float:
        return self.cost_without_eur - self.cost_with_eur


def _has_counter_source(closed: dict[str, Any]) -> bool:
    sources = closed["ist_power_source"]
    return any(sources[channel] == _SOURCE_COUNTER for channel in _MEAN_OR_COUNTER_CHANNELS)


def _sources_allowed(sources: Any) -> bool:
    if not isinstance(sources, dict):
        return False
    return all(
        sources.get(channel) in (_SOURCE_MEAN, _SOURCE_COUNTER)
        for channel in _MEAN_OR_COUNTER_CHANNELS
    ) and all(sources.get(channel) == _SOURCE_MEAN for channel in _MEAN_ONLY_CHANNELS)


def ledger_house_kw(closed: dict[str, Any]) -> float:
    """House load the ledger books for a counted slot (spec § 4).

    All means: the logged ``house_kw``. With an energy counter on pv or grid the logged
    value is a sample mean that no longer fits the counter deltas, and the shadow
    plant would see another load than the real one. The balance
    ``pv + grid + battery`` keeps the load equal on both sides.
    """
    if _has_counter_source(closed):
        return float(closed["pv_kw"]) + float(closed["grid_kw"]) + float(closed["battery_kw"])
    return float(closed["house_kw"])


def slot_skip_reason(closed: dict[str, Any] | None) -> str | None:
    """Why a ``closed_interval`` does not count, or ``None`` when it does.

    A slot counts when it is present, has at least ``MIN_SAMPLE_COUNT_FOR_MEAN``
    samples (same bar as "Ist bisher"), pv and grid are slot means or energy
    counters, battery and house are slot means, and the powers the slot needs are
    present (``battery_kw`` too with a counter, see ``ledger_house_kw``). A slot whose
    plant powers all read exactly zero is a meter outage (``is_dead_telemetry_snapshot``,
    as the history chart treats it) and does not count either.
    """
    if not isinstance(closed, dict) or not closed:
        return SKIP_MISSING
    try:
        samples = int(closed.get("sample_count") or 0)
    except (TypeError, ValueError):
        return SKIP_FEW_SAMPLES
    if samples < MIN_SAMPLE_COUNT_FOR_MEAN:
        return SKIP_FEW_SAMPLES
    if not _sources_allowed(closed.get("ist_power_source")):
        return SKIP_NOT_MEAN
    required = _REQUIRED_POWER_KEYS
    if _has_counter_source(closed):
        required = (*_REQUIRED_POWER_KEYS, "battery_kw")
    for key in required:
        value = closed.get(key)
        if value is None or isinstance(value, bool):
            return SKIP_NO_POWER
        try:
            float(value)
        except (TypeError, ValueError):
            return SKIP_NO_POWER
    if is_dead_telemetry_snapshot(closed):
        return SKIP_DEAD_TELEMETRY
    return None


def shadow_battery_params(battery_params: dict | list[dict] | None) -> dict:
    """Battery the shadow plant runs: one ESS as is, several aggregated like the baseline."""
    batteries = coerce_battery_params_list(battery_params)
    if not batteries:
        raise ValueError("savings ledger: no house battery parameters for the shadow plant")
    if len(batteries) == 1:
        return batteries[0]
    return aggregate_battery_params_for_load(batteries)


def _cost_eur(grid_kwh: float, k_act_cent: float, k_push_cent: float) -> float:
    if grid_kwh >= 0.0:
        return grid_kwh * k_act_cent / 100.0
    return grid_kwh * k_push_cent / 100.0


def _shadow_step(
    pv_kw: float,
    house_kw: float,
    shadow_soc: float | None,
    battery_params: dict | None,
    dt: float,
) -> tuple[float | None, float, float]:
    """``(soc_next, battery_kw, grid_kwh)`` of the shadow plant in one slot.

    With a battery: vendor mode on the load plus standby. Without one (v2, spec § 7):
    ``grid = load - pv`` and no SoC. The causal step and the day replay share this
    function, so a replay on the logged timing gives the causal slots to the bit.
    """
    if battery_params is None:
        return None, 0.0, (house_kw - pv_kw) * dt
    load_kw = house_kw + bat.standby_power_kw(battery_params)
    soc_next, batt_kw = bat.vendor_mode_step(
        float(shadow_soc), pv_kw - load_kw, battery_params, dt_h=dt
    )
    grid_shadow_kw = load_kw - pv_kw + batt_kw
    return soc_next, batt_kw, grid_shadow_kw * dt


def advance_slot(
    closed: dict[str, Any] | None,
    shadow_soc: float | None,
    battery_params: dict | None,
    *,
    k_act_cent: float,
    k_push_cent: float,
    dt_h: float = DEFAULT_DT_H,
) -> LedgerSlot:
    """Price one closed slot with and without Earnie and step the shadow battery.

    ``battery_params`` is the shadow battery (``shadow_battery_params``); ``None`` (with
    ``shadow_soc`` ``None``) is a house without battery, v2 only.
    ``k_act_cent`` / ``k_push_cent`` are the buy and sell prices of that slot's
    cycle. A slot that does not count (``slot_skip_reason``) is skipped on both
    sides: zero cost, shadow SoC unchanged, ``skip_reason`` set.
    """
    dt = validate_dt_h(dt_h)
    reason = slot_skip_reason(closed)
    if reason is not None:
        return LedgerSlot(
            counted=False,
            skip_reason=reason,
            cost_with_eur=0.0,
            cost_without_eur=0.0,
            shadow_soc_next=shadow_soc,
            import_kwh_with=0.0,
            import_kwh_without=0.0,
            export_kwh_with=0.0,
            export_kwh_without=0.0,
            shadow_battery_kw=0.0,
        )
    assert closed is not None
    pv_kw = float(closed["pv_kw"])
    house_kw = ledger_house_kw(closed)
    grid_kw = float(closed["grid_kw"])
    soc_next, batt_kw, grid_shadow_kwh = _shadow_step(pv_kw, house_kw, shadow_soc, battery_params, dt)
    grid_kwh = grid_kw * dt
    k_act = float(k_act_cent)
    k_push = float(k_push_cent)
    return LedgerSlot(
        counted=True,
        skip_reason=None,
        cost_with_eur=_cost_eur(grid_kwh, k_act, k_push),
        cost_without_eur=_cost_eur(grid_shadow_kwh, k_act, k_push),
        shadow_soc_next=soc_next,
        import_kwh_with=max(grid_kwh, 0.0),
        import_kwh_without=max(grid_shadow_kwh, 0.0),
        export_kwh_with=max(-grid_kwh, 0.0),
        export_kwh_without=max(-grid_shadow_kwh, 0.0),
        shadow_battery_kw=batt_kw,
    )


# --- SA-day close (Ledger P4) -------------------------------------------------

INCOMPLETE_COVERAGE = 0.8

P_REF_IMPORT_WEIGHTED = "import_weighted"
P_REF_TIME_MEAN = "time_mean"
P_REF_CARRIED = "carried"
# v2 without house battery: no shadow SoC, no SoC correction (spec § 7).
P_REF_NO_BATTERY = "no_battery"

CHAIN_FIRST_RUN = "first_run"
CHAIN_STATE_UNREADABLE = "state_unreadable"
CHAIN_SAVINGS_V_CHANGED = "savings_v_changed"
CHAIN_BACKFILL = "backfill"

DayBounds = Callable[[datetime], tuple[datetime, datetime]]
# v2: consumers, profiles and windows of the day a state holds open (I/O lives with the caller,
# ``savings_ledger_store.flex_day_provider``); called once per closed day.
DayFlex = Callable[["LedgerState"], FlexDayInputs]


@dataclass(frozen=True)
class LedgerInput:
    """One closed slot as the ledger sees it.

    ``slot_start`` is timezone-aware. ``k_act_cent`` / ``k_push_cent`` are the
    buy and sell prices of that slot's own log entry; ``None`` when the entry is
    missing (the slot is then skipped with ``no_price``). ``planned_flex_kw`` is
    the slot-0 plan of that entry per consumer. ``filter_native`` is the native filter
    window the cycle used per consumer (``native_start_hour``, ``native_duration_hours``
    from the entry's ``filter_contexts``); the v2 day replay takes it as the filter's
    unshifted timing.
    """

    slot_start: datetime
    closed: dict[str, Any] | None
    k_act_cent: float | None
    k_push_cent: float | None
    planned_flex_kw: dict[str, float] = field(default_factory=dict)
    filter_native: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerState:
    """Shadow chain and the open SA-day; JSON round trip via ``to_dict`` / ``from_dict``."""

    savings_v: int
    chain_start: datetime
    chain_start_reason: str
    shadow_soc: float | None
    day_start: datetime
    day_end: datetime
    last_slot_start: datetime | None
    soc_actual_end: float | None
    prev_correction_eur: float | None
    slots: tuple[dict[str, Any], ...]
    days_closed: int = 0
    # Prices and slot-0 plan of the newest cycle, kept until its slot is closed
    # (the daemon hook; see ``savings_ledger_store.pending_slot_from_entry``).
    pending_slot: dict[str, Any] | None = None
    # v2: chain SoC at the start of the open day, where its replay starts (plan § 4.1).
    # ``shadow_soc`` runs on causally through the open day (D2). ``None`` without battery.
    shadow_soc_day_start: float | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = {
            "savings_v": self.savings_v,
            "chain_start": self.chain_start.isoformat(),
            "chain_start_reason": self.chain_start_reason,
            "shadow_soc": self.shadow_soc,
            "day_start": self.day_start.isoformat(),
            "day_end": self.day_end.isoformat(),
            "last_slot_start": self.last_slot_start.isoformat() if self.last_slot_start else None,
            "soc_actual_end": self.soc_actual_end,
            "prev_correction_eur": self.prev_correction_eur,
            "slots": [dict(s) for s in self.slots],
            "days_closed": self.days_closed,
            "pending_slot": dict(self.pending_slot) if self.pending_slot else None,
        }
        if self.savings_v >= SAVINGS_V_REPLAY:
            raw["shadow_soc_day_start"] = self.shadow_soc_day_start
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LedgerState":
        """Strict: a missing or malformed field raises (the caller starts a new chain)."""
        last = raw["last_slot_start"]
        soc_end = raw["soc_actual_end"]
        prev = raw["prev_correction_eur"]
        slots = raw["slots"]
        if not isinstance(slots, list) or not all(isinstance(s, dict) for s in slots):
            raise ValueError("savings ledger state: slots must be a list of objects")
        pending = raw.get("pending_slot")
        if pending is not None and not isinstance(pending, dict):
            raise ValueError("savings ledger state: pending_slot must be an object")
        savings_v = int(raw["savings_v"])
        soc = raw["shadow_soc"]
        day_start_soc = None
        if savings_v >= SAVINGS_V_REPLAY:
            day_start_soc = raw["shadow_soc_day_start"]
            if (soc is None) != (day_start_soc is None):
                raise ValueError(
                    "savings ledger state: shadow_soc and shadow_soc_day_start disagree on the battery"
                )
        elif soc is None:
            raise ValueError("savings ledger state: shadow_soc missing (a chain without battery needs v2)")
        return cls(
            savings_v=savings_v,
            chain_start=_aware(raw["chain_start"]),
            chain_start_reason=str(raw["chain_start_reason"]),
            shadow_soc=float(soc) if soc is not None else None,
            day_start=_aware(raw["day_start"]),
            day_end=_aware(raw["day_end"]),
            last_slot_start=_aware(last) if last is not None else None,
            soc_actual_end=float(soc_end) if soc_end is not None else None,
            prev_correction_eur=float(prev) if prev is not None else None,
            slots=tuple(dict(s) for s in slots),
            days_closed=int(raw["days_closed"]),
            pending_slot=dict(pending) if pending else None,
            shadow_soc_day_start=float(day_start_soc) if day_start_soc is not None else None,
        )


def _aware(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        raise ValueError(f"savings ledger state: timestamp without offset: {value!r}")
    return moment


def start_chain(
    inp: LedgerInput,
    day_bounds: DayBounds,
    *,
    reason: str,
    savings_v: int = SAVINGS_V,
    with_battery: bool = True,
) -> LedgerState | None:
    """New shadow chain at the actual SoC of ``inp`` (its ``soc_start_percent``).

    Returns ``None`` when the slot has no SoC; the caller tries the next slot.
    The slot itself is not booked here; pass it to ``advance`` next.
    ``with_battery=False`` starts a chain without shadow battery (v2 only, spec § 7).
    """
    if inp.slot_start.tzinfo is None:
        raise ValueError("savings ledger: slot_start must be timezone-aware")
    if not with_battery and savings_v < SAVINGS_V_REPLAY:
        raise ValueError(f"savings ledger: a chain without battery needs savings_v >= {SAVINGS_V_REPLAY}")
    soc: float | None = None
    if with_battery:
        raw_soc = (inp.closed or {}).get("soc_start_percent")
        if raw_soc is None:
            return None
        soc = float(raw_soc)
    day_start, day_end = day_bounds(inp.slot_start)
    return LedgerState(
        savings_v=savings_v,
        chain_start=inp.slot_start,
        chain_start_reason=reason,
        shadow_soc=soc,
        day_start=day_start,
        day_end=day_end,
        last_slot_start=None,
        soc_actual_end=None,
        prev_correction_eur=None,
        slots=(),
        shadow_soc_day_start=soc if savings_v >= SAVINGS_V_REPLAY else None,
    )


@dataclass(frozen=True)
class DayClose:
    """A closed SA-day: its ledger row and the state that held it.

    ``closing`` is the state the slot file record comes from (``day_slots_record``): in v1
    the state before the close, in v2 the replayed one (its slot rows carry the replay's
    ``cost_without_eur`` and shadow SoC, so the slots add up to the row).
    ``chain_soc`` is the shadow SoC the chain continues with.
    """

    row: dict[str, Any]
    closing: "LedgerState"
    chain_soc: float | None


def advance(
    state: LedgerState,
    inp: LedgerInput,
    battery_params: dict | None,
    day_bounds: DayBounds,
    *,
    app_version: str,
    dt_h: float = DEFAULT_DT_H,
    day_flex: DayFlex | None = None,
) -> tuple[LedgerState, dict[str, Any] | None]:
    """Book one closed slot; returns the new state and the row of a day this slot closed.

    See ``advance_with_slots``, which also returns the closed day's slot source.
    """
    state, closed_day = advance_with_slots(
        state, inp, battery_params, day_bounds, app_version=app_version, dt_h=dt_h, day_flex=day_flex
    )
    return state, closed_day.row if closed_day is not None else None


def advance_with_slots(
    state: LedgerState,
    inp: LedgerInput,
    battery_params: dict | None,
    day_bounds: DayBounds,
    *,
    app_version: str,
    dt_h: float = DEFAULT_DT_H,
    day_flex: DayFlex | None = None,
) -> tuple[LedgerState, DayClose | None]:
    """Book one closed slot; returns the new state and the day this slot closed.

    A slot at or after ``state.day_end`` first closes the open day (``close_open_day``),
    then opens the SA-day that contains the slot. Days without any slot get no row.
    A slot at or before the last booked one is ignored (replay after a restart).
    ``day_bounds(moment)`` returns the sunrise-to-sunrise day that contains
    ``moment``; a slot belongs to the day its start lies in (as Chart 2 books it).
    ``day_flex`` is needed when a v2 state closes a day (the replay); v1 never calls it.
    """
    if inp.slot_start.tzinfo is None:
        raise ValueError("savings ledger: slot_start must be timezone-aware")
    if state.last_slot_start is not None and inp.slot_start <= state.last_slot_start:
        return state, None
    closed_day = None
    if inp.slot_start >= state.day_end:
        closed_day = close_open_day(
            state, battery_params, app_version=app_version, dt_h=dt_h, day_flex=day_flex
        )
        day_start, day_end = day_bounds(inp.slot_start)
        replay = state.savings_v >= SAVINGS_V_REPLAY
        state = replace(
            state,
            day_start=day_start,
            day_end=day_end,
            soc_actual_end=None,
            prev_correction_eur=closed_day.row["soc_correction_eur"],
            slots=(),
            days_closed=state.days_closed + 1,
            shadow_soc=closed_day.chain_soc,
            shadow_soc_day_start=closed_day.chain_soc if replay else None,
        )
    if inp.k_act_cent is None or inp.k_push_cent is None:
        slot = LedgerSlot(
            counted=False,
            skip_reason=SKIP_NO_PRICE,
            cost_with_eur=0.0,
            cost_without_eur=0.0,
            shadow_soc_next=state.shadow_soc,
            import_kwh_with=0.0,
            import_kwh_without=0.0,
            export_kwh_with=0.0,
            export_kwh_without=0.0,
            shadow_battery_kw=0.0,
        )
    else:
        slot = advance_slot(
            inp.closed,
            state.shadow_soc,
            battery_params,
            k_act_cent=inp.k_act_cent,
            k_push_cent=inp.k_push_cent,
            dt_h=dt_h,
        )
    soc_actual_end = state.soc_actual_end
    closed = inp.closed or {}
    if slot.counted and closed.get("soc_end_percent") is not None:
        soc_actual_end = float(closed["soc_end_percent"])
    state = replace(
        state,
        shadow_soc=slot.shadow_soc_next,
        last_slot_start=inp.slot_start,
        soc_actual_end=soc_actual_end,
        slots=state.slots + (_slot_row(inp, slot, dt_h),),
    )
    return state, closed_day


def record_error_slot(state: LedgerState, slot_start: datetime) -> LedgerState:
    """Book a slot the hook could not process as skipped (``error``); the day row counts it in ``errors``.

    The shadow SoC stays; a slot of a later day than the open one is left out (the
    next regular slot closes the day).
    """
    if state.last_slot_start is not None and slot_start <= state.last_slot_start:
        return state
    if not (state.day_start <= slot_start < state.day_end):
        return state
    row = {
        "slot_start": slot_start.isoformat(),
        "counted": False,
        "skip_reason": SKIP_ERROR,
        "cost_with_eur": 0.0,
        "cost_without_eur": 0.0,
        "import_kwh_with": 0.0,
        "import_kwh_without": 0.0,
        "export_kwh_with": 0.0,
        "export_kwh_without": 0.0,
        "k_act_cent": None,
        "k_push_cent": None,
        "shadow_soc_end": state.shadow_soc,
        "house_kwh": 0.0,
        "pv_kwh": 0.0,
    }
    return replace(state, last_slot_start=slot_start, slots=state.slots + (row,))


def _slot_row(inp: LedgerInput, slot: LedgerSlot, dt_h: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slot_start": inp.slot_start.isoformat(),
        "counted": slot.counted,
        "skip_reason": slot.skip_reason,
        "cost_with_eur": slot.cost_with_eur,
        "cost_without_eur": slot.cost_without_eur,
        "import_kwh_with": slot.import_kwh_with,
        "import_kwh_without": slot.import_kwh_without,
        "export_kwh_with": slot.export_kwh_with,
        "export_kwh_without": slot.export_kwh_without,
        "k_act_cent": inp.k_act_cent,
        # Sell price and PV of the slot: the v2 day replay steps the shadow plant again from the rows.
        "k_push_cent": inp.k_push_cent,
        "shadow_soc_end": slot.shadow_soc_next,
        # A skipped slot counts as zero, like its costs; a counted one has its load (``slot_skip_reason``).
        "house_kwh": 0.0,
        "pv_kwh": 0.0,
    }
    if slot.counted:
        closed = inp.closed or {}
        row["house_kwh"] = ledger_house_kw(closed) * dt_h
        row["pv_kwh"] = float(closed["pv_kw"]) * dt_h
        row["flex_planned_kwh"] = {
            str(cid): float(kw) * dt_h for cid, kw in (inp.planned_flex_kw or {}).items()
        }
        row["flex_delivered_kwh"] = {
            str(cid): float(kw or 0.0) * dt_h for cid, kw in (closed.get("flex_kw") or {}).items()
        }
        if inp.filter_native:
            row["filter_native"] = {str(cid): dict(window) for cid, window in inp.filter_native.items()}
    return row


def _grid_slot_starts(day_start: datetime, day_end: datetime, dt_h: float) -> list[datetime]:
    """Slot starts in ``[day_start, day_end)`` on the quarter-hour grid."""
    step = timedelta(hours=dt_h)
    minutes = int(step.total_seconds() // 60)
    first = day_start.replace(minute=(day_start.minute // minutes) * minutes, second=0, microsecond=0)
    if first < day_start:
        first += step
    starts = []
    moment = first
    while moment < day_end:
        starts.append(moment)
        moment += step
    return starts


def _slots_in_day(day_start: datetime, day_end: datetime, dt_h: float) -> int:
    """Number of slot starts in ``[day_start, day_end)`` on the quarter-hour grid."""
    return len(_grid_slot_starts(day_start, day_end, dt_h))


def _unbooked_slot_reasons(state: LedgerState, dt_h: float) -> dict[str, int]:
    """Grid slots of the open day without a booked slot row, per reason.

    A slot before the chain start is ``before_chain``; any other slot without a
    row had no completed cycle (``no_cycle``).
    """
    booked = {datetime.fromisoformat(str(s["slot_start"])) for s in state.slots}
    reasons: dict[str, int] = {}
    for moment in _grid_slot_starts(state.day_start, state.day_end, dt_h):
        if moment in booked:
            continue
        reason = SKIP_BEFORE_CHAIN if moment < state.chain_start else SKIP_NO_CYCLE
        reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _sum_flex(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    total: dict[str, float] = {}
    for row in rows:
        for cid, kwh in (row.get(key) or {}).items():
            total[cid] = total.get(cid, 0.0) + float(kwh)
    return {cid: round(kwh, 3) for cid, kwh in sorted(total.items()) if abs(kwh) >= 0.0005}


def close_day(
    state: LedgerState,
    battery_params: dict | None,
    *,
    app_version: str,
    dt_h: float = DEFAULT_DT_H,
) -> dict[str, Any]:
    """Ledger row (spec § 4) for the open day of ``state``.

    SoC correction ``(soc_actual_end − soc_shadow_end) / 100 · capacity · efficiency · p_ref``
    with ``p_ref`` the import-weighted mean buy price of the counted slots (actual
    import), or their time mean on a day without import. A day without a counted
    slot or without an actual SoC carries the previous correction unchanged
    (``p_ref_basis: carried``): its correction terms cancel and the telescoping
    sum stays intact.

    Rows are taken as they are: the causal slots (v1, and the open day's provisional
    figures in v2), or the replayed slots (``close_open_day``). Without a house battery
    (v2) there is no SoC correction (``p_ref_basis: no_battery``).
    """
    counted = [s for s in state.slots if s["counted"]]
    slots_total = _slots_in_day(state.day_start, state.day_end, dt_h)
    cost_with = sum(s["cost_with_eur"] for s in counted)
    cost_without = sum(s["cost_without_eur"] for s in counted)
    import_with = sum(s["import_kwh_with"] for s in counted)
    prev = state.prev_correction_eur if state.prev_correction_eur is not None else 0.0
    p_ref: float | None = None
    if counted and import_with > 0.0:
        p_ref = sum(s["import_kwh_with"] * s["k_act_cent"] for s in counted) / import_with
        basis = P_REF_IMPORT_WEIGHTED
    elif counted:
        p_ref = sum(s["k_act_cent"] for s in counted) / len(counted)
        basis = P_REF_TIME_MEAN
    if battery_params is None:
        if state.savings_v < SAVINGS_V_REPLAY:
            raise ValueError(f"savings ledger: a day without battery needs savings_v >= {SAVINGS_V_REPLAY}")
        p_ref = None
        correction = 0.0
        prev = 0.0
        basis = P_REF_NO_BATTERY
    elif p_ref is None or state.soc_actual_end is None:
        correction = prev
        basis = P_REF_CARRIED
    else:
        energy_kwh = (
            (state.soc_actual_end - state.shadow_soc)
            / 100.0
            * float(battery_params["battery_capacity_kwh"])
            * float(battery_params["efficiency"])
        )
        correction = energy_kwh * p_ref / 100.0
    saving = cost_without - cost_with
    coverage = len(counted) / slots_total if slots_total else 0.0
    skipped = _unbooked_slot_reasons(state, dt_h)
    for s in state.slots:
        if not s["counted"]:
            skipped[s["skip_reason"]] = skipped.get(s["skip_reason"], 0) + 1
    row: dict[str, Any] = {
        "savings_v": state.savings_v,
        "chain_start": state.chain_start.isoformat(),
        "day_start": state.day_start.isoformat(),
        "day_end": state.day_end.isoformat(),
        "slots_total": slots_total,
        "slots_present": len(counted),
        "slots_skipped": dict(sorted(skipped.items())),
        "errors": skipped.get(SKIP_ERROR, 0),
        "coverage": round(coverage, 3),
        "incomplete": coverage < INCOMPLETE_COVERAGE,
        "cost_with_eur": round(cost_with, 4),
        "cost_without_eur": round(cost_without, 4),
        "saving_eur": round(saving, 4),
        "soc_actual_end_pct": state.soc_actual_end,
        "soc_shadow_end_pct": round(state.shadow_soc, 2) if state.shadow_soc is not None else None,
        "p_ref_cent": round(p_ref, 3) if p_ref is not None else None,
        "p_ref_basis": basis,
        "soc_correction_eur": round(correction, 4),
        "soc_correction_prev_eur": round(prev, 4),
        "saving_adjusted_eur": round(saving + correction - prev, 4),
        "import_kwh_with": round(import_with, 3),
        "import_kwh_without": round(sum(s["import_kwh_without"] for s in counted), 3),
        "export_kwh_with": round(sum(s["export_kwh_with"] for s in counted), 3),
        "export_kwh_without": round(sum(s["export_kwh_without"] for s in counted), 3),
        "flex_planned_kwh": _sum_flex(counted, "flex_planned_kwh"),
        "flex_delivered_kwh": _sum_flex(counted, "flex_delivered_kwh"),
        "app_version": app_version,
    }
    if state.days_closed == 0:
        row["chain_start_reason"] = state.chain_start_reason
    return row


# --- Day replay (savings_v 2, Ledger P9c) -------------------------------------


def _delivered_kw(row: dict[str, Any], dt_h: float) -> dict[str, float]:
    return {cid: float(kwh) / dt_h for cid, kwh in (row.get("flex_delivered_kwh") or {}).items()}


def replay_day(
    slots: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    start_soc: float | None,
    battery_params: dict | None,
    flex_retimed_kw: list[dict[str, float]] | None,
    *,
    dt_h: float,
) -> tuple[tuple[dict[str, Any], ...], float | None]:
    """Shadow plant over one day's slot rows from ``start_soc``; returns the replayed rows and the end SoC.

    ``flex_retimed_kw`` (one dict per row, kW per consumer) replaces each consumer's delivered
    power: ``house_without = house + sum(retimed - delivered)`` per counted slot (plan § 1).
    ``None`` keeps the logged timing, which gives the causal slots to the bit. Skipped rows stay
    zero and keep the SoC. A counted row without ``house_kwh``, ``pv_kwh`` or the prices raises
    ``KeyError`` (a row from before Ledger P9b; v2 starts a new chain, so none reaches here).
    """
    if flex_retimed_kw is not None and len(flex_retimed_kw) != len(slots):
        raise ValueError(f"savings ledger replay: {len(flex_retimed_kw)} flex rows for {len(slots)} slots")
    dt = validate_dt_h(dt_h)
    soc = start_soc
    out: list[dict[str, Any]] = []
    for index, row in enumerate(slots):
        replayed = dict(row)
        if not row["counted"]:
            replayed["shadow_soc_end"] = soc
            out.append(replayed)
            continue
        house_kw = float(row["house_kwh"]) / dt
        if flex_retimed_kw is not None:
            delivered = _delivered_kw(row, dt)
            retimed = flex_retimed_kw[index]
            shift = sum(retimed.get(cid, 0.0) - delivered.get(cid, 0.0) for cid in set(retimed) | set(delivered))
            house_kw += shift
        soc, _batt_kw, grid_kwh = _shadow_step(float(row["pv_kwh"]) / dt, house_kw, soc, battery_params, dt)
        k_act = float(row["k_act_cent"])
        k_push = float(row["k_push_cent"])
        replayed["cost_without_eur"] = _cost_eur(grid_kwh, k_act, k_push)
        replayed["import_kwh_without"] = max(grid_kwh, 0.0)
        replayed["export_kwh_without"] = max(-grid_kwh, 0.0)
        replayed["shadow_soc_end"] = soc
        out.append(replayed)
    return tuple(out), soc


def _flex_retimed_kwh(per_slot_kw: list[dict[str, float]], dt_h: float) -> dict[str, float]:
    total: dict[str, float] = {}
    for slot in per_slot_kw:
        for cid, kw in slot.items():
            total[cid] = total.get(cid, 0.0) + kw * dt_h
    return {cid: round(kwh, 3) for cid, kwh in sorted(total.items()) if abs(kwh) >= 0.0005}


def close_open_day(
    state: LedgerState,
    battery_params: dict | None,
    *,
    app_version: str,
    dt_h: float = DEFAULT_DT_H,
    day_flex: DayFlex | None = None,
) -> DayClose:
    """Close the open day of ``state``: v1 from the causal slots, v2 by replaying the day (plan § 4.1).

    v2: the flex consumers are re-timed (``retime_flex_day``), the shadow plant runs over the
    day from ``shadow_soc_day_start`` and the row, the slot record and the chain SoC come from
    that replay. A second replay on the logged timing from the same start SoC gives
    ``saving_logged_timing_eur`` (D4).
    """
    if state.savings_v < SAVINGS_V_REPLAY:
        row = close_day(state, battery_params, app_version=app_version, dt_h=dt_h)
        return DayClose(row, state, state.shadow_soc)
    if day_flex is None:
        raise ValueError("savings ledger: closing a v2 day needs the day's flex inputs (day_flex)")
    if (battery_params is None) != (state.shadow_soc_day_start is None):
        raise ValueError("savings ledger: battery parameters and the chain's shadow SoC disagree")
    inputs = day_flex(state)
    retiming = retime_flex_day(
        state.slots, inputs.consumers, inputs.profiles_kw, inputs.windows, dt_h=dt_h
    )
    replayed, end_soc = replay_day(
        state.slots, state.shadow_soc_day_start, battery_params, retiming.per_slot_kw, dt_h=dt_h
    )
    logged, _ = replay_day(state.slots, state.shadow_soc_day_start, battery_params, None, dt_h=dt_h)
    closing = replace(state, slots=replayed, shadow_soc=end_soc)
    row = close_day(closing, battery_params, app_version=app_version, dt_h=dt_h)
    logged_saving = sum(s["cost_without_eur"] - s["cost_with_eur"] for s in logged if s["counted"])
    row["flex_retimed_kwh"] = _flex_retimed_kwh(retiming.per_slot_kw, dt_h)
    row["flex_timing"] = dict(sorted(retiming.timing.items()))
    row["flex_logged_reasons"] = dict(sorted(retiming.logged_reasons.items()))
    row["saving_logged_timing_eur"] = round(logged_saving, 4)
    row["flex_native_window_source"] = {
        cid: window.native_source
        for cid, window in sorted(inputs.windows.items())
        if window.native_source is not None
    }
    return DayClose(row, closing, end_soc)


# --- Slot series of closed days (Account view P1) -----------------------------

_DAY_SLOT_FIELDS = (
    "slot_start",
    "counted",
    "skip_reason",
    "cost_with_eur",
    "cost_without_eur",
    "house_kwh",
)


def day_slots_record(state: LedgerState) -> dict[str, Any]:
    """Slot file record for the open day of ``state`` (the state before ``advance`` closed it).

    A slot row without one of ``_DAY_SLOT_FIELDS`` raises ``KeyError``: the slots
    an older version left in the state have no ``house_kwh``.
    """
    return {
        "savings_v": state.savings_v,
        "chain_start": state.chain_start.isoformat(),
        "day_start": state.day_start.isoformat(),
        "day_end": state.day_end.isoformat(),
        "slots": [{key: slot[key] for key in _DAY_SLOT_FIELDS} for slot in state.slots],
    }


def check_day_slots(row: dict[str, Any], record: dict[str, Any]) -> None:
    """Raise ``ValueError`` unless the slots of ``record`` add up to the ledger ``row``."""
    slots = record["slots"]
    counted = sum(1 for slot in slots if slot["counted"])
    if counted != row["slots_present"]:
        raise ValueError(
            f"day {row['day_start']}: {counted} counted slots, the ledger row has {row['slots_present']}"
        )
    for key in ("cost_with_eur", "cost_without_eur"):
        total = round(sum(float(slot[key]) for slot in slots), 4)
        if total != float(row[key]):
            raise ValueError(f"day {row['day_start']}: slots sum {key} {total}, the ledger row has {row[key]}")


def lifetime_summary(rows: list[dict[str, Any]], chain_start: datetime) -> dict[str, Any]:
    """Lifetime total of one chain: Σ ``saving_adjusted_eur`` over its closed days."""
    key = chain_start.isoformat()
    chain = [r for r in rows if r.get("chain_start") == key and r.get("savings_v") == SAVINGS_V]
    return {
        "savings_v": SAVINGS_V,
        "chain_start": key,
        "days": len(chain),
        "incomplete_days": sum(1 for r in chain if r.get("incomplete")),
        "slots_present": sum(int(r["slots_present"]) for r in chain),
        "saving_adjusted_eur": round(sum(float(r["saving_adjusted_eur"]) for r in chain), 4),
    }
