"""Backtesting: Matrixbau und Sunset-Schritte (Jetzt→SA₂, SOC_min am Sonnenaufgang)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from data.planning_window import (
    compute_planning_window,
    normalize_hour_slot,
    sunrise_anchor_slot_index,
)
from simulation.horizon_mode import BACKTESTING_STEP_HOURS


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


def window_start_before_anchor(anchor: datetime, timezone_name: str) -> datetime:
    """Start des 24h-Backtesting-Schritts (entspricht erstem Slot des fixed_24h-Fensters)."""
    tz = ZoneInfo(timezone_name)
    start = anchor - timedelta(hours=BACKTESTING_STEP_HOURS)
    if start.tzinfo is None:
        return start.replace(tzinfo=tz)
    return start.astimezone(tz)


def compute_sunset_planning_at_anchor(
    anchor: datetime,
    scenario_params: dict,
) -> tuple[object, int]:
    """
    Sunset-MILP-Fenster ab Fensterstart (Anker−24h).

    Returns: (PlanningWindow, sunrise_soc_min_index)
    """
    lat, lon, tz_name = geo_params_from_scenario(scenario_params)
    now = window_start_before_anchor(anchor, tz_name)
    window = compute_planning_window(now, lat, lon, tz_name)
    if len(window.slot_datetimes) < BACKTESTING_STEP_HOURS:
        raise ValueError(
            f"Sunset-Planungsfenster ab {now} hat nur {len(window.slot_datetimes)} h, "
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


def effective_sunrise_soc_min_index(sunrise_soc_min_index: int) -> int | None:
    """SOC_min am Sonnenaufgang nur, wenn der Anker innerhalb des 24h-Output-Schritts liegt."""
    if sunrise_soc_min_index >= BACKTESTING_STEP_HOURS:
        return None
    return sunrise_soc_min_index


def truncate_matrix_for_step_simulation(
    matrix: list[dict],
    sunrise_soc_min_index: int,
) -> list[dict]:
    """
    Kürzt die Sunset-Matrix auf den 24h-Output-Schritt.

    Volle Jetzt→SA₂-Matrix (typ. 36–39 h) würde simulate_horizon pro Extra-Stunde
    ein zusätzliches MILP lösen, obwohl Backtesting nur 24 h ausgibt.
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
    Übernimmt stündliche Grundlast/Total aus dem 24h-Schritt in die Sunset-Output-Matrix.

    Die volle SA₂-Matrix skaliert resolve_hourly_baseload_kw über alle Planungsstunden;
    Plausibilität und fairer Vergleich zu fixed_24h verlangen die 24h-Werte.
    """
    by_slot = {_slot_lookup_key(row["slot_datetime"]): row for row in step_matrix}
    missing: list[str] = []
    for row in output_matrix:
        key = _slot_lookup_key(row["slot_datetime"])
        source = by_slot.get(key)
        if source is None:
            missing.append(key.isoformat())
            continue
        row["expected_p_act"] = source["expected_p_act"]
        row["expected_p_total"] = source["expected_p_total"]
    if missing:
        raise ValueError(
            "Sunset-Output-Matrix: fehlende Schritt-Slots für Grundlast-Overlay: "
            + ", ".join(missing[:5])
            + (" ..." if len(missing) > 5 else "")
        )
