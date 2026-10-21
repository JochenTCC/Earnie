"""Backtesting: Matrixbau und Sunrise-Buchungsschritte (ready_by-Tag → SA₂).

Defaults when not set explicitly
--------------------------------
- Book / ``fixed_24h`` step length: ``BACKTESTING_STEP_HOURS`` (= **24**) from
  ``simulation.horizon_mode`` (used by ``window_start_before_anchor``,
  ``step_slot_datetimes``, truncate helpers).
- Timezone for sun times: ``config.get_planning_timezone()`` (live scenario /
  ``timezone_name`` in config) — not read from ``scenario_params``.
- ``latitude`` / ``longitude``: **no defaults**; required in scenario settings
  (``backtesting_scenarios.json``), else ``geo_params_from_scenario`` raises.
- SE product horizon mode default (``sunrise_window``) lives in
  ``simulation.horizon_mode.DEFAULT_HORIZON_MODE``, not in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config
from data.planning_window import (
    compute_planning_window,
    hourly_slots_inclusive,
    official_sun_times,
    sunrise_anchor_slot_index,
)
from simulation.horizon_mode import BACKTESTING_STEP_HOURS


BOOK_PERIOD_KEY = "_book_period"
"""Scenario-param key ``(start, end_exclusive)`` (naive datetimes): book only slots inside.

The sunrise chain spans ``[SA(start−1), SA(end+1))``, so its first and last book
reach over the period edges. Booking only the in-period part of those two steps
(targets, flex window and reference slots all follow ``book_slots``) keeps the
period exactly ``[start 00:00, end+1 00:00)`` without a clip that would drop
consumption the optimizer shifted across the edge.
"""


@dataclass(frozen=True)
class SunriseBookStep:
    """One SE sunrise_window step keyed by ready_by.

    ``book_slots`` is [SA₁, SA₂), cut to the book period at the chain edges
    (``BOOK_PERIOD_KEY``); ``sa1_index`` is the MILP index of its first slot.
    """

    ready_by: datetime
    sa0: datetime
    sa1: datetime
    sa2: datetime
    milp_slots: tuple[datetime, ...]
    book_slots: tuple[datetime, ...]
    sa1_index: int

    @property
    def book_hours(self) -> int:
        return len(self.book_slots)

    @property
    def milp_hours(self) -> int:
        return len(self.milp_slots)


def naive_backtesting_slot(moment: datetime) -> datetime:
    """Backtesting fuel uses naive local timestamps; keep QH minutes."""
    from optimizer.slot_duration import normalize_quarter_hour_slot

    slot = normalize_quarter_hour_slot(moment)
    if slot.tzinfo is not None:
        return slot.replace(tzinfo=None)
    return slot


def geo_params_from_scenario(scenario_params: dict) -> tuple[float, float, str]:
    """
    Latitude, Longitude und Zeitzone für Sonnenzeiten im Backtesting.

    ``latitude`` / ``longitude`` must be set in scenario settings (no default).
    Timezone defaults to ``config.get_planning_timezone()`` when not supplied
    here (this helper never reads timezone from ``scenario_params``).
    """
    lat = scenario_params.get("latitude")
    lon = scenario_params.get("longitude")
    if lat is None or lon is None:
        raise ValueError(
            "Sunset-Backtesting erfordert latitude und longitude im Szenario "
            "(backtesting_scenarios.json settings)."
        )
    tz_name = config.get_planning_timezone()
    return float(lat), float(lon), tz_name


def _aware_ready_by(ready_by: datetime, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if ready_by.tzinfo is None:
        return ready_by.replace(tzinfo=tz)
    return ready_by.astimezone(tz)


def hourly_slots_half_open(start: datetime, end: datetime) -> tuple[datetime, ...]:
    """Planning slots with start inclusive and end exclusive (QH floor since 2.5.e)."""
    from optimizer.slot_duration import normalize_quarter_hour_slot, slot_step

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start und end müssen timezone-aware sein.")
    slot = normalize_quarter_hour_slot(start)
    end_slot = normalize_quarter_hour_slot(end)
    if end_slot <= slot:
        raise ValueError(f"Leeres Halb-offen-Intervall: [{slot}, {end_slot}).")
    step = slot_step()
    slots: list[datetime] = []
    while slot < end_slot:
        slots.append(slot)
        slot += step
    return tuple(slots)


def _sunrise_on(day: date, latitude: float, longitude: float, timezone_name: str) -> datetime:
    sunrise, _sunset = official_sun_times(day, latitude, longitude, timezone_name)
    return sunrise


def resolve_ready_by_sunrise_step(
    ready_by: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
    *,
    book_period: tuple[datetime, datetime] | None = None,
) -> SunriseBookStep:
    """
    Book the sunrise day that ends on ready_by's calendar date; MILP SA₀→SA₂.

    SA₂ = sunrise on ``ready_by.date()``, SA₁ / SA₀ = sunrise one / two days
    earlier; book [SA₁, SA₂). The window depends only on the calendar date, so
    consecutive days form a contiguous sunrise chain (book k starts where k−1
    ended) whatever ready_by's clock time (07:00 weekday, 12:00 weekend) and
    whether it lies before or after that day's sunrise.

    ready_by is only the EV deadline: its charging night (evening before →
    SA₂) lies inside the book, so EV target and charging slots share a window.
    """
    ready = _aware_ready_by(ready_by, timezone_name)
    day = ready.date()
    sa2 = _sunrise_on(day, latitude, longitude, timezone_name)
    sa1 = _sunrise_on(day - timedelta(days=1), latitude, longitude, timezone_name)
    sa0 = _sunrise_on(day - timedelta(days=2), latitude, longitude, timezone_name)
    if not (sa0 < sa1 < sa2):
        raise ValueError(
            f"Sonnenaufgänge nicht aufsteigend für ready_by {ready.isoformat()}: "
            f"SA₀ {sa0.isoformat()}, SA₁ {sa1.isoformat()}, SA₂ {sa2.isoformat()}."
        )
    from optimizer.slot_duration import normalize_quarter_hour_slot

    milp_slots = hourly_slots_inclusive(sa0, sa2)
    book_slots = hourly_slots_half_open(sa1, sa2)
    if book_period is not None:
        period_start, period_end = book_period
        book_slots = tuple(
            slot
            for slot in book_slots
            if period_start <= naive_backtesting_slot(slot) < period_end
        )
        if not book_slots:
            raise ValueError(
                f"Sunrise-Buchung [{sa1.isoformat()}, {sa2.isoformat()}) liegt "
                f"außerhalb der Buchungsperiode [{period_start}, {period_end})."
            )
    book_start_slot = normalize_quarter_hour_slot(book_slots[0])
    try:
        sa1_index = milp_slots.index(book_start_slot)
    except ValueError as exc:
        raise ValueError(
            f"Buchungsstart {book_start_slot.isoformat()} fehlt in MILP-Slots "
            f"{milp_slots[0].isoformat()}…{milp_slots[-1].isoformat()}."
        ) from exc
    return SunriseBookStep(
        ready_by=ready,
        sa0=sa0,
        sa1=sa1,
        sa2=sa2,
        milp_slots=milp_slots,
        book_slots=book_slots,
        sa1_index=sa1_index,
    )


def resolve_sunrise_book_step_for_scenario(
    ready_by: datetime,
    scenario_params: dict,
) -> SunriseBookStep:
    lat, lon, tz_name = geo_params_from_scenario(scenario_params)
    return resolve_ready_by_sunrise_step(
        ready_by,
        lat,
        lon,
        tz_name,
        book_period=scenario_params.get(BOOK_PERIOD_KEY),
    )


def window_start_before_anchor(anchor: datetime, timezone_name: str) -> datetime:
    """Start des 24h-Backtesting-Schritts (entspricht erstem Slot des fixed_24h-Fensters)."""
    tz = ZoneInfo(timezone_name)
    start = anchor - timedelta(hours=BACKTESTING_STEP_HOURS)
    if start.tzinfo is None:
        return start.replace(tzinfo=tz)
    return start.astimezone(tz)


def compute_sunrise_planning_at_anchor(
    anchor: datetime,
    scenario_params: dict,
) -> tuple[object, int]:
    """
    Legacy helper: Sunrise-MILP-Fenster ab Anker−24h.

    Prefer resolve_ready_by_sunrise_step for SE sunrise_window.
    """
    lat, lon, tz_name = geo_params_from_scenario(scenario_params)
    now = window_start_before_anchor(anchor, tz_name)
    window = compute_planning_window(now, lat, lon, tz_name)
    from optimizer.slot_duration import DEFAULT_DT_H, slots_for_wall_hours

    min_slots = slots_for_wall_hours(float(BACKTESTING_STEP_HOURS), DEFAULT_DT_H)
    if len(window.slot_datetimes) < min_slots:
        raise ValueError(
            f"Sunrise-Planungsfenster ab {now} hat nur {len(window.slot_datetimes)} Slots, "
            f"benötigt mindestens {min_slots} ({BACKTESTING_STEP_HOURS} h)."
        )
    return window, sunrise_anchor_slot_index(window)


def step_slot_datetimes(anchor: datetime, timezone_name: str) -> list[datetime]:
    """24 wall-clock hours [Anker−24h, Anker) as QH slots — fair vs fixed_24h."""
    from optimizer.slot_duration import DEFAULT_DT_H, slots_for_wall_hours

    start = window_start_before_anchor(anchor, timezone_name)
    n = slots_for_wall_hours(float(BACKTESTING_STEP_HOURS), DEFAULT_DT_H)
    step = timedelta(hours=DEFAULT_DT_H)
    slots = [
        naive_backtesting_slot(start + step * index)
        for index in range(n)
    ]
    return slots


def effective_sunrise_soc_min_index(sunrise_soc_min_index: int | None) -> int | None:
    """SOC_min am Sonnenaufgang nur, wenn der Anker innerhalb des 24h-Output-Schritts liegt."""
    from optimizer.slot_duration import DEFAULT_DT_H, slots_for_wall_hours

    if sunrise_soc_min_index is None:
        return None
    step_slots = slots_for_wall_hours(float(BACKTESTING_STEP_HOURS), DEFAULT_DT_H)
    if sunrise_soc_min_index >= step_slots:
        return None
    return sunrise_soc_min_index


def truncate_matrix_for_step_simulation(
    matrix: list[dict],
    sunrise_soc_min_index: int,
) -> list[dict]:
    """
    Kürzt die Sunset-Matrix auf den 24h-Output-Schritt (legacy truncate path).
    """
    from optimizer.slot_duration import DEFAULT_DT_H, slots_for_wall_hours

    step_slots = slots_for_wall_hours(float(BACKTESTING_STEP_HOURS), DEFAULT_DT_H)
    if len(matrix) <= step_slots:
        return matrix
    return matrix[:step_slots]


def overlay_step_consumption_on_matrix(
    output_matrix: list[dict],
    step_matrix: list[dict],
) -> None:
    """
    Übernimmt Grundlast/Total aus dem Buchungs-Schritt in die MILP-Matrix.

    Iterates book/step rows and updates matching QH MILP rows. SA₀ foresight
    rows without book fuel are left unchanged.
    """
    by_output = {
        naive_backtesting_slot(row["slot_datetime"]): row for row in output_matrix
    }
    missing: list[str] = []
    for source in step_matrix:
        key = naive_backtesting_slot(source["slot_datetime"])
        target = by_output.get(key)
        if target is None:
            missing.append(key.isoformat())
            continue
        target["expected_p_act"] = source["expected_p_act"]
        target["expected_p_total"] = source["expected_p_total"]
    if missing:
        unique = sorted(set(missing))
        raise ValueError(
            "Sunrise-Overlay: Buchungs-Slots fehlen in der MILP-Matrix: "
            + ", ".join(unique[:5])
            + ("…" if len(unique) > 5 else "")
        )
