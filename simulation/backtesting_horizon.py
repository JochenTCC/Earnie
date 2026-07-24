"""Backtesting: Matrixbau und Sunrise-Buchungsschritte (ready_by → SA₂)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from data.planning_window import (
    compute_planning_window,
    hourly_slots_inclusive,
    next_sunrise_after,
    normalize_hour_slot,
    previous_sunrise_before,
    sunrise_anchor_slot_index,
)
from simulation.horizon_mode import BACKTESTING_STEP_HOURS


@dataclass(frozen=True)
class SunriseBookStep:
    """One SE sunrise_window step keyed by ready_by."""

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
    """Backtesting cons_data_hourly.csv nutzt naive lokale Zeitstempel."""
    slot = normalize_hour_slot(moment)
    if slot.tzinfo is not None:
        return slot.replace(tzinfo=None)
    return slot


def geo_params_from_scenario(scenario_params: dict) -> tuple[float, float, str]:
    """Latitude, Longitude und Zeitzone für Sonnenzeiten im Backtesting."""
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
    """Hourly slots with start inclusive and end exclusive (floor hours)."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start und end müssen timezone-aware sein.")
    slot = normalize_hour_slot(start)
    end_slot = normalize_hour_slot(end)
    if end_slot <= slot:
        raise ValueError(f"Leeres Halb-offen-Intervall: [{slot}, {end_slot}).")
    slots: list[datetime] = []
    while slot < end_slot:
        slots.append(slot)
        slot += timedelta(hours=1)
    return tuple(slots)


def resolve_ready_by_sunrise_step(
    ready_by: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> SunriseBookStep:
    """
    SA₂ = first sunrise strictly after ready_by; book [SA₁, SA₂); MILP SA₀→SA₂.

    ready_by must lie strictly between SA₁ and SA₂.
    """
    ready = _aware_ready_by(ready_by, timezone_name)
    sa2 = next_sunrise_after(ready, latitude, longitude, timezone_name)
    sa1 = previous_sunrise_before(
        sa2 - timedelta(seconds=1), latitude, longitude, timezone_name
    )
    sa0 = previous_sunrise_before(
        sa1 - timedelta(seconds=1), latitude, longitude, timezone_name
    )
    if not (sa1 < ready < sa2):
        raise ValueError(
            f"ready_by {ready.isoformat()} liegt nicht strikt zwischen "
            f"SA₁ {sa1.isoformat()} und SA₂ {sa2.isoformat()}."
        )
    milp_slots = hourly_slots_inclusive(sa0, sa2)
    book_slots = hourly_slots_half_open(sa1, sa2)
    sa1_floor = normalize_hour_slot(sa1)
    sa1_index = next(
        (
            index
            for index, slot in enumerate(milp_slots)
            if normalize_hour_slot(slot) == sa1_floor
        ),
        None,
    )
    if sa1_index is None:
        raise ValueError(
            f"SA₁ {sa1_floor.isoformat()} fehlt in MILP-Slots "
            f"{milp_slots[0].isoformat()}…{milp_slots[-1].isoformat()}."
        )
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
    return resolve_ready_by_sunrise_step(ready_by, lat, lon, tz_name)


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
    if len(window.slot_datetimes) < BACKTESTING_STEP_HOURS:
        raise ValueError(
            f"Sunrise-Planungsfenster ab {now} hat nur {len(window.slot_datetimes)} h, "
            f"benötigt mindestens {BACKTESTING_STEP_HOURS}."
        )
    return window, sunrise_anchor_slot_index(window)


def step_slot_datetimes(anchor: datetime, timezone_name: str) -> list[datetime]:
    """24 Stunden [Anker−24h, Anker) — identisch zu fixed_24h für fairen Vergleich."""
    start = window_start_before_anchor(anchor, timezone_name)
    slots = [
        naive_backtesting_slot(start + timedelta(hours=index))
        for index in range(BACKTESTING_STEP_HOURS)
    ]
    return slots


def effective_sunrise_soc_min_index(sunrise_soc_min_index: int | None) -> int | None:
    """SOC_min am Sonnenaufgang nur, wenn der Anker innerhalb des 24h-Output-Schritts liegt."""
    if sunrise_soc_min_index is None:
        return None
    if sunrise_soc_min_index >= BACKTESTING_STEP_HOURS:
        return None
    return sunrise_soc_min_index


def truncate_matrix_for_step_simulation(
    matrix: list[dict],
    sunrise_soc_min_index: int,
) -> list[dict]:
    """
    Kürzt die Sunset-Matrix auf den 24h-Output-Schritt (legacy truncate path).
    """
    if len(matrix) <= BACKTESTING_STEP_HOURS:
        return matrix
    return matrix[:BACKTESTING_STEP_HOURS]


def _slot_lookup_key(moment: datetime) -> datetime:
    return naive_backtesting_slot(normalize_hour_slot(moment))


def overlay_step_consumption_on_matrix(
    output_matrix: list[dict],
    step_matrix: list[dict],
) -> None:
    """
    Übernimmt stündliche Grundlast/Total aus dem Buchungs-Schritt in die MILP-Matrix.
    """
    by_out = {_slot_lookup_key(row["slot_datetime"]): row for row in output_matrix}
    missing: list[str] = []
    for source in step_matrix:
        key = _slot_lookup_key(source["slot_datetime"])
        row = by_out.get(key)
        if row is None:
            missing.append(key.isoformat())
            continue
        row["expected_p_act"] = source["expected_p_act"]
        row["expected_p_total"] = source["expected_p_total"]
    if missing:
        raise ValueError(
            "Sunrise-Output-Matrix: fehlende Buchungs-Slots in MILP-Matrix: "
            + ", ".join(missing[:5])
            + (" ..." if len(missing) > 5 else "")
        )
