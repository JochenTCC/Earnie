"""SE load consistency: profile-spec window load vs. hourly reference load.

Optimised scenarios plan against ``baseload + flex targets`` (profile_spec); the
reference runs use the hourly model of the same profile. Both are meant to describe
the same total load. A consumer whose schedule cannot be delivered inside its start
window (e.g. a 24 h run starting at 12:00 with a 6 h shift) silently loses energy in
the spec path — this check names such consumers.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from optimizer.slot_duration import energy_kwh_from_kw

LOAD_TOLERANCE_REL = 0.03
_CONSUMER_MIN_ABS_KWH = 50.0
_CONSUMER_MIN_REL = 0.10


def profile_spec_vs_reference(
    profile: dict,
    anchors: list[datetime],
    *,
    climate=None,
    tolerance: float = LOAD_TOLERANCE_REL,
) -> dict:
    """Compare Σ spec (baseload + flex targets) with Σ reference load over all windows.

    Returns ``{"status": "ok" | "deviation", "message": str | None, ...}`` with
    per-consumer ``consumers`` rows ``(id, reference_kwh, spec_kwh)`` for flex consumers.
    """
    from house_config.planning_flex_bridge import (
        collect_planning_flex_consumers,
        milp_flex_thermal_annual_ids,
        resolve_profile_spec_flex_targets,
    )
    from house_config.planning_flex_overlays import (
        house_profile_baseload_overlay,
        profile_flat_baseload_kw,
    )
    from data.consumption_profiles import modeled_consumer_kw_at_datetime
    from simulation.engine import window_slot_datetimes

    flex = collect_planning_flex_consumers(profile)
    flex_ids = {consumer["id"] for consumer in flex}
    thermal_ids = milp_flex_thermal_annual_ids(flex)
    consumers = list(profile.get("consumers", []))

    reference_total = 0.0
    spec_baseload = 0.0
    targets: Counter[str] = Counter()
    reference_by_flex: Counter[str] = Counter()
    for anchor in anchors:
        slots = window_slot_datetimes(anchor)
        for consumer in consumers:
            kwh = energy_kwh_from_kw(
                modeled_consumer_kw_at_datetime(consumer, slot, climate=climate)
                for slot in slots
            )
            reference_total += kwh
            if consumer.get("id") in flex_ids:
                reference_by_flex[consumer["id"]] += kwh
        flat = profile_flat_baseload_kw(profile)
        reference_total += energy_kwh_from_kw(flat for _ in slots)
        overlay = house_profile_baseload_overlay(
            profile,
            slots,
            historical_totals=None,
            cons_data_consumer_ids=set(),
            milp_flex_thermal_ids=thermal_ids,
            climate=climate,
        )
        spec_baseload += energy_kwh_from_kw(flat + extra for extra in overlay)
        for cid, kwh in resolve_profile_spec_flex_targets(
            flex, profile, slots, window_end=anchor, climate=climate
        ).items():
            targets[cid] += kwh

    spec_total = spec_baseload + sum(targets.values())
    deviation = (spec_total - reference_total) / reference_total if reference_total > 0 else 0.0
    rows = [
        (cid, round(reference_by_flex[cid], 1), round(targets.get(cid, 0.0), 1))
        for cid in sorted(flex_ids)
    ]
    result = {
        "status": "ok",
        "message": None,
        "reference_kwh": round(reference_total, 1),
        "spec_kwh": round(spec_total, 1),
        "deviation_rel": round(deviation, 4),
        "consumers": rows,
    }
    if abs(deviation) <= tolerance:
        return result

    lines = []
    # The absolute threshold is defined per year; scale it to the number of windows.
    min_abs = _CONSUMER_MIN_ABS_KWH * len(anchors) / 365.0
    for cid, reference_kwh, spec_kwh in rows:
        delta = spec_kwh - reference_kwh
        if abs(delta) >= min_abs and abs(delta) / max(reference_kwh, 1.0) >= _CONSUMER_MIN_REL:
            lines.append(f"{cid}: Plan-Ziel {spec_kwh:.0f} statt {reference_kwh:.0f} kWh ({delta:+.0f})")
    detail = ("; ".join(lines) + ". ") if lines else ""
    result["status"] = "deviation"
    result["message"] = (
        f"Optimierungs-Last ({spec_total:.0f} kWh) weicht um {deviation:+.1%} von der "
        f"Referenz-Last ({reference_total:.0f} kWh) ab. {detail}"
        "Prüfe Dauer, Startzeit und Verschiebung der genannten Verbraucher "
        "(Lauf muss in das Startfenster passen)."
    )
    return result
