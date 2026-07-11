"""Brücke Hausprofil-generic → Backtesting (fixe Blöcke + MILP-Flex)."""
from __future__ import annotations

from datetime import date, datetime

from house_config.generic_schedule import (
    generic_daily_target_kwh_for_day,
    generic_hourly_kw_for_day,
    is_fixed_start,
)


def _house_generic_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "generic" and consumer.get("schedule")
    ]


def split_planning_generic_consumers(
    house_profile: dict,
) -> tuple[list[dict], list[dict]]:
    """Teilt generic-Verbraucher in fixe (shift=0) und MILP-flexible."""
    fixed: list[dict] = []
    flex: list[dict] = []
    for consumer in _house_generic_consumers(house_profile):
        schedule = consumer["schedule"]
        if is_fixed_start(float(schedule.get("start_shift_h", 0.0) or 0.0)):
            fixed.append(consumer)
        else:
            flex.append(planning_consumer_to_milp(consumer))
    return fixed, flex


def planning_consumer_to_milp(consumer: dict) -> dict:
    schedule = consumer["schedule"]
    duration_h = float(schedule["duration_h"])
    min_on_quarterhours = max(4, int(round(duration_h * 4)))
    nominal = float(consumer["nominal_power_kw"])
    return {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label", consumer["id"])),
        "nominal_power_kw": nominal,
        "min_power_kw": nominal,
        "min_on_quarterhours": min_on_quarterhours,
        "daily_target_kwh": 0.0,
        "daily_target_source": "config",
        "signal_type": "binary",
        "log_signal_type": "binary",
        "optimizer_enabled": True,
        "generic_flex_window": {
            "start_hour": int(schedule["start_hour"]) % 24,
            "start_shift_h": float(schedule.get("start_shift_h", 0.0) or 0.0),
            "duration_h": duration_h,
        },
    }


def _house_thermal_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "thermal_annual"
    ]


def thermal_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
) -> list[float]:
    """Summiert kW thermischer Verbraucher (on/off bei nominal_power_kw) je Slot."""
    thermal = _house_thermal_consumers(house_profile)
    if not thermal:
        return [0.0] * len(slot_datetimes)
    from data.consumption_profiles import _modeled_consumer_hourly_kw

    profiles = [
        _modeled_consumer_hourly_kw(consumer, hours=8760)
        for consumer in thermal
    ]
    ref_start = datetime(2023, 1, 1)
    overlay: list[float] = []
    for slot_dt in slot_datetimes:
        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        hour_index = int((naive - ref_start).total_seconds() // 3600) % 8760
        kw = sum(profile[hour_index] for profile in profiles)
        overlay.append(round(kw, 6))
    return overlay


def house_profile_baseload_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
) -> list[float]:
    """Fixe generic- und thermische Verbraucher aus Hausprofil je Slot."""
    generic = fixed_generic_hourly_overlay(house_profile, slot_datetimes)
    thermal = thermal_hourly_overlay(house_profile, slot_datetimes)
    return [round(g + t, 6) for g, t in zip(generic, thermal)]


def fixed_generic_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
) -> list[float]:
    """Summiert kW fixer generic-Verbraucher je Slot."""
    fixed, _flex = split_planning_generic_consumers(house_profile)
    if not fixed:
        return [0.0] * len(slot_datetimes)
    overlay = [0.0] * len(slot_datetimes)
    for slot_index, slot_dt in enumerate(slot_datetimes):
        day = slot_dt.date()
        hour = slot_dt.hour
        for consumer in fixed:
            day_hourly = generic_hourly_kw_for_day(consumer, day)
            overlay[slot_index] += day_hourly[hour]
    return overlay


def planning_flex_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
) -> dict[str, float]:
    """Tagesziele (kWh) für Planungs-Flex-Verbraucher im Fenster."""
    if not flex_consumers:
        return {}
    by_id = {consumer["id"]: consumer for consumer in _house_generic_consumers(house_profile)}
    targets: dict[str, float] = {}
    dates = {slot_dt.date() for slot_dt in slot_datetimes}
    for milp_consumer in flex_consumers:
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        total = sum(
            generic_daily_target_kwh_for_day(source, day)
            for day in dates
        )
        targets[milp_consumer["id"]] = round(total, 3)
    return targets


def merge_flexible_consumers(
    base_consumers: list[dict],
    planning_consumers: list[dict],
) -> list[dict]:
    """Config-Verbraucher + Planungs-Verbraucher ohne ID-Kollision."""
    merged = list(base_consumers)
    taken = {consumer["id"] for consumer in base_consumers}
    for consumer in planning_consumers:
        if consumer["id"] in taken:
            continue
        merged.append(consumer)
        taken.add(consumer["id"])
    return merged
