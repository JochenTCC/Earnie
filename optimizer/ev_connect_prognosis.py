"""EV connect / coming-back prognosis phases (unplugged + forecast_when_absent).

See docs/spec/ev-return-prognosis.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from optimizer.charging_schedule import (
    charging_deadline_after,
    config_day_schedule,
    deadline_from_ready_hour,
    next_scheduled_availability,
    parse_loxone_ready_by_time,
    resolve_charging_deadline,
    _window_start_for_day,
)
from optimizer.charging_urgent import latest_start_datetime

# Extra connect buffer after last possible charge start (late return prognosis).
LATE_RETURN_CONNECT_BUFFER_H = 1.0

PHASE_OPEN_CYCLE = "open_cycle"
PHASE_OVERNIGHT_OPEN = "overnight_open"
PHASE_BEFORE_ARRIVAL = "before_arrival"
PHASE_LATE_RETURN = "late_return"
PHASE_INACTIVE = "inactive"

READY_AT_LIVE = "live"
READY_AT_CONFIG = "config"


@dataclass(frozen=True)
class ConnectPrognosis:
    """Result of ``resolve_connect_prognosis`` for an unplugged EV."""

    phase: str
    available_from: datetime | None
    deadline: datetime | None
    ready_at_source: str | None
    inactive_reason: str | None = None


def _today_connect_slot_missed(horizon_start: datetime, consumer: dict) -> bool:
    """True when today's config car_available_from_hour is already before now."""
    today_from = _window_start_for_day(
        consumer, horizon_start.date(), reference=horizon_start
    )
    return today_from is not None and today_from < horizon_start


def late_return_available_from(
    horizon_start: datetime,
    consumer: dict,
    *,
    scheduled_from: datetime | None,
    deadline: datetime,
    target_kwh: float,
    max_kw: float,
) -> datetime | None:
    """
    After a missed config connect slot (or next arrival after ReadyAt), use
    ReadyAt − charge duration − 1h as internal available_from (clamped to now).
    """
    if scheduled_from is None:
        return None
    if scheduled_from <= horizon_start:
        return scheduled_from
    missed = _today_connect_slot_missed(horizon_start, consumer)
    if not missed and scheduled_from < deadline:
        return scheduled_from
    last = latest_start_datetime(
        deadline, float(target_kwh), float(max_kw)
    ) - timedelta(hours=LATE_RETURN_CONNECT_BUFFER_H)
    return max(horizon_start, last)


def _absent_availability_for_day_offset(
    horizon_start: datetime,
    consumer: dict,
    day_offset: int,
    ready_raw: str | float | None,
) -> datetime | None:
    """One (0, -1) day-offset candidate for overnight-open detection."""
    day = horizon_start.date() + timedelta(days=day_offset)
    window_start = _window_start_for_day(consumer, day, reference=horizon_start)
    if window_start is None or window_start > horizon_start:
        return None
    deadline, _ = resolve_charging_deadline(
        consumer,
        window_start,
        window_start,
        ready_raw=ready_raw,
    )
    if deadline is None or horizon_start >= deadline:
        return None
    if window_start.date() >= horizon_start.date():
        return None
    today_from = _window_start_for_day(
        consumer, horizon_start.date(), reference=horizon_start
    )
    if today_from is not None and horizon_start >= today_from:
        return None
    # FertigUm parsed from yesterday's window_start can push the overnight
    # deadline into daytime (e.g. "Morgen, 11:00" → 11:00). Only treat the
    # overnight cycle as still open before the *config* ready_by.
    config_deadline = charging_deadline_after(window_start, consumer)
    if config_deadline is not None and horizon_start >= config_deadline:
        return None
    return horizon_start


def _open_cycle_keeps_available_now(
    horizon_start: datetime,
    open_cycle_deadline: datetime | None,
) -> bool:
    """Brief same-day unplug before FertigUm keeps available_from=now."""
    from optimizer.charging_session import deadline_reached

    if open_cycle_deadline is None:
        return False
    if deadline_reached(horizon_start, open_cycle_deadline):
        return False
    return horizon_start.date() == open_cycle_deadline.date()


def resolve_absent_availability(
    horizon_start: datetime,
    consumer: dict,
    *,
    ready_raw: str | float | None = None,
    open_cycle_deadline: datetime | None = None,
) -> datetime | None:
    """
    Baseline connect time when unplugged (no ReadyAt rewrite).

    After today's connect slot passes, returns the next ``car_available_from_hour``.
    Callers should prefer ``resolve_connect_prognosis`` for full late-return handling.
    """
    if _open_cycle_keeps_available_now(horizon_start, open_cycle_deadline):
        return horizon_start
    for day_offset in (0, -1):
        found = _absent_availability_for_day_offset(
            horizon_start, consumer, day_offset, ready_raw
        )
        if found is not None:
            return found
    return next_scheduled_availability(horizon_start, consumer)


def resolve_ready_at(
    horizon_start: datetime,
    consumer: dict,
    *,
    ready_raw: str | float | None = None,
) -> tuple[datetime | None, str | None]:
    """Live FertigUm, else config ready_by after horizon; else (None, None)."""
    live = parse_loxone_ready_by_time(ready_raw, horizon_start)
    if live is not None and live > horizon_start:
        return live, READY_AT_LIVE
    day_sched = config_day_schedule(consumer, horizon_start)
    config_dl = deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
    if config_dl is not None and config_dl > horizon_start:
        return config_dl, READY_AT_CONFIG
    return None, None


def _inactive(reason: str) -> ConnectPrognosis:
    return ConnectPrognosis(
        phase=PHASE_INACTIVE,
        available_from=None,
        deadline=None,
        ready_at_source=None,
        inactive_reason=reason,
    )


def _phase_with_ready_at(
    phase: str,
    available_from: datetime,
    horizon_start: datetime,
    consumer: dict,
    *,
    ready_raw: str | float | None,
    open_cycle_deadline: datetime | None = None,
) -> ConnectPrognosis:
    deadline: datetime | None = None
    source: str | None = None
    if (
        phase == PHASE_OPEN_CYCLE
        and open_cycle_deadline is not None
        and open_cycle_deadline > horizon_start
    ):
        deadline = open_cycle_deadline
        source = READY_AT_LIVE
    if deadline is None:
        deadline, source = resolve_ready_at(
            horizon_start, consumer, ready_raw=ready_raw
        )
    if deadline is None or deadline <= horizon_start:
        return _inactive("keine gültige Fertigstellungszeit")
    if deadline <= available_from:
        return _inactive("keine gültige Fertigstellungszeit")
    return ConnectPrognosis(
        phase=phase,
        available_from=available_from,
        deadline=deadline,
        ready_at_source=source,
    )


def resolve_connect_prognosis(
    horizon_start: datetime,
    consumer: dict,
    *,
    ready_raw: str | float | None = None,
    open_cycle_deadline: datetime | None = None,
    target_kwh: float,
    max_kw: float,
) -> ConnectPrognosis:
    """
    Single connect-phase resolver for Loxone and config absent paths.

    Requires ``target_kwh > 0`` and ``max_kw > 0`` for late-return math.
    """
    if target_kwh is None or float(target_kwh) <= 0:
        return _inactive("kein Ladeziel")
    if max_kw is None or float(max_kw) <= 0:
        return _inactive("keine Ladeleistung")

    if _open_cycle_keeps_available_now(horizon_start, open_cycle_deadline):
        return _phase_with_ready_at(
            PHASE_OPEN_CYCLE,
            horizon_start,
            horizon_start,
            consumer,
            ready_raw=ready_raw,
            open_cycle_deadline=open_cycle_deadline,
        )

    for day_offset in (0, -1):
        overnight = _absent_availability_for_day_offset(
            horizon_start, consumer, day_offset, ready_raw
        )
        if overnight is not None:
            return _phase_with_ready_at(
                PHASE_OVERNIGHT_OPEN,
                overnight,
                horizon_start,
                consumer,
                ready_raw=ready_raw,
            )

    scheduled_from = next_scheduled_availability(horizon_start, consumer)
    if scheduled_from is None:
        return _inactive("kein car_available_from_hour in Config")

    deadline, ready_source = resolve_ready_at(
        horizon_start, consumer, ready_raw=ready_raw
    )
    if deadline is None or deadline <= horizon_start:
        return _inactive("keine gültige Fertigstellungszeit")

    available_from = late_return_available_from(
        horizon_start,
        consumer,
        scheduled_from=scheduled_from,
        deadline=deadline,
        target_kwh=float(target_kwh),
        max_kw=float(max_kw),
    )
    if available_from is None or deadline <= available_from:
        return _inactive("keine gültige Fertigstellungszeit")

    missed = _today_connect_slot_missed(horizon_start, consumer)
    if not missed and available_from == scheduled_from and scheduled_from > horizon_start:
        phase = PHASE_BEFORE_ARRIVAL
    elif available_from == scheduled_from and scheduled_from <= horizon_start:
        # scheduled already "now" from overnight-style baseline (should be rare here)
        phase = PHASE_BEFORE_ARRIVAL
    else:
        phase = PHASE_LATE_RETURN

    return ConnectPrognosis(
        phase=phase,
        available_from=available_from,
        deadline=deadline,
        ready_at_source=ready_source,
    )


def absent_source_label(
    *,
    path: str,
    ready_at_source: str | None,
) -> str:
    """Map ReadyAt source to charging-context source_label (loxone|config path)."""
    if path == "loxone":
        if ready_at_source == READY_AT_LIVE:
            return "loxone (abwesend, Prognose + FertigUm Loxone)"
        if ready_at_source == READY_AT_CONFIG:
            return "loxone (abwesend, Prognose + ReadyAt Config)"
        return "loxone (abwesend, Prognose)"
    if ready_at_source == READY_AT_LIVE:
        return "config.json (abwesend, Prognose + FertigUm Loxone)"
    if ready_at_source == READY_AT_CONFIG:
        return "config.json (abwesend, Prognose + ReadyAt Config)"
    return "config.json (abwesend, Prognose)"
