"""Brücke Hausprofil-generic → Backtesting (fixe Blöcke + MILP-Flex)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from settings.flexible_consumers import CONSUMER_PALETTE_SIZE
from house_config.generic_schedule import (
    generic_daily_target_kwh_for_day,
    generic_hourly_kw_for_day,
    is_fixed_start,
)

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext

PROFILE_SPEC = "profile_spec"
LOGGED_DAY = "logged_day"
CONSUMPTION_SOURCES = frozenset({PROFILE_SPEC, LOGGED_DAY})


def resolve_consumption_source(scenario_params: dict | None) -> str:
    """profile_spec = Hausprofil-Spec für Optimierung; logged_day = cons_data-Replay."""
    if not scenario_params:
        return LOGGED_DAY
    explicit = str(scenario_params.get("consumption_source", "") or "").strip()
    if explicit in CONSUMPTION_SOURCES:
        return explicit
    if scenario_params.get("_house_profile"):
        return PROFILE_SPEC
    return LOGGED_DAY


def profile_flat_baseload_kw(house_profile: dict) -> float:
    """Konstante Grundlast (kW) aus profile.baseload_kwh."""
    return float(house_profile.get("baseload_kwh", 0.0) or 0.0) / 8760.0


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


def _house_ev_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "ev" and consumer.get("charging_schedule")
    ]


def planning_ev_to_milp(consumer: dict) -> dict:
    """Hausprofil-EV → flexible_consumers-Shape für MILP (ohne Loxone)."""
    sched = consumer["charging_schedule"]
    min_on = max(1, int(consumer.get("min_on_quarterhours", 4) or 4))
    min_power = float(consumer.get("min_power_kw", 0.0) or 0.0)
    capacity = float(consumer["battery_capacity_kwh"])
    return {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label", consumer["id"])),
        "nominal_power_kw": float(consumer["nominal_power_kw"]),
        "min_power_kw": min_power if min_power > 0 else None,
        "min_on_quarterhours": min_on,
        "signal_type": "power",
        "log_signal_type": "power",
        "optimizer_enabled": True,
        "daily_target_kwh": 0.0,
        "daily_target_source": "config",
        "battery_capacity_kwh": capacity,
        "charging_schedule": {
            "enabled": True,
            "forecast_when_absent": bool(sched.get("forecast_when_absent", True)),
            "target_soc_percent": float(sched.get("target_soc_percent", 100.0)),
            "charging_efficiency": float(sched.get("charging_efficiency", 0.95)),
            "weekday": dict(sched.get("weekday") or {}),
            "weekend": dict(sched.get("weekend") or {}),
            "battery_capacity_kwh": capacity,
        },
        "path_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
        "loxone_target_kwh_name": "",
        "loxone_target_hours_name": "",
    }


def planning_ev_consumers(house_profile: dict) -> list[dict]:
    """EV-Verbraucher aus Hausprofil als MILP-flexible Verbraucher."""
    return [planning_ev_to_milp(consumer) for consumer in _house_ev_consumers(house_profile)]


def collect_planning_flex_consumers(house_profile: dict) -> list[dict]:
    """Generic MILP-flex + EV für Szenario-Auflösung."""
    _fixed, flex_generic = split_planning_generic_consumers(house_profile)
    return flex_generic + planning_ev_consumers(house_profile)


def planning_ev_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """Tagesziele (kWh) für EV-Verbraucher im Fenster."""
    from house_config.ev_profile import ev_daily_kwh

    ev_by_id = {
        consumer["id"]: consumer
        for consumer in _house_ev_consumers(house_profile)
    }
    if not ev_by_id:
        return {}
    targets: dict[str, float] = {}
    for milp_consumer in flex_consumers:
        source = ev_by_id.get(milp_consumer["id"])
        if not source:
            continue
        if window_end is not None:
            departure_day = window_end.date()
            targets[milp_consumer["id"]] = round(
                ev_daily_kwh(source, departure_day), 3
            )
            continue
        dates = {slot_dt.date() for slot_dt in slot_datetimes}
        targets[milp_consumer["id"]] = round(
            sum(ev_daily_kwh(source, day) for day in dates),
            3,
        )
    return targets


def _house_thermal_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "thermal_annual"
    ]


def _house_profile_consumer_ids(house_profile: dict) -> set[str]:
    return {
        str(consumer.get("id") or "")
        for consumer in house_profile.get("consumers", [])
        if consumer.get("id")
    }


def _consumer_ids_with_cons_data(
    house_profile: dict,
    historical_totals: dict[str, float] | None = None,
    *,
    cons_data_consumer_ids: set[str] | None = None,
) -> set[str]:
    """Verbraucher-IDs, deren kWh bereits aus cons_data-Spalten stammen."""
    house_ids = _house_profile_consumer_ids(house_profile)
    if cons_data_consumer_ids is not None:
        return house_ids & cons_data_consumer_ids

    present: set[str] = set()
    totals = historical_totals or {}
    for cid in house_ids:
        if float(totals.get(cid, 0.0) or 0.0) > 0.0:
            present.add(cid)
    return present


def thermal_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    skip_consumer_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Summiert kW thermischer Verbraucher (on/off bei nominal_power_kw) je Slot."""
    thermal = _house_thermal_consumers(house_profile)
    if not thermal:
        return [0.0] * len(slot_datetimes)
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    skip = skip_consumer_ids or set()
    active = [
        consumer
        for consumer in thermal
        if str(consumer.get("id") or "") not in skip
    ]
    if not active:
        return [0.0] * len(slot_datetimes)
    overlay: list[float] = []
    for slot_dt in slot_datetimes:
        kw = sum(
            modeled_consumer_kw_at_datetime(consumer, slot_dt, climate=climate)
            for consumer in active
        )
        overlay.append(round(kw, 6))
    return overlay


def house_profile_baseload_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    historical_totals: dict[str, float] | None = None,
    cons_data_consumer_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Fixe generic- und thermische Verbraucher aus Hausprofil je Slot."""
    skip_ids = _consumer_ids_with_cons_data(
        house_profile,
        historical_totals,
        cons_data_consumer_ids=cons_data_consumer_ids,
    )
    generic = fixed_generic_hourly_overlay(house_profile, slot_datetimes, skip_ids=skip_ids)
    thermal = thermal_hourly_overlay(
        house_profile,
        slot_datetimes,
        skip_consumer_ids=skip_ids,
        climate=climate,
    )
    return [round(g + t, 6) for g, t in zip(generic, thermal)]


def fixed_generic_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    skip_ids: set[str] | None = None,
) -> list[float]:
    """Summiert kW fixer generic-Verbraucher je Slot."""
    fixed, _flex = split_planning_generic_consumers(house_profile)
    if not fixed:
        return [0.0] * len(slot_datetimes)
    skip = skip_ids or set()
    overlay = [0.0] * len(slot_datetimes)
    for slot_index, slot_dt in enumerate(slot_datetimes):
        day = slot_dt.date()
        hour = slot_dt.hour
        for consumer in fixed:
            cid = str(consumer.get("id") or "")
            if cid in skip:
                continue
            day_hourly = generic_hourly_kw_for_day(consumer, day)
            overlay[slot_index] += day_hourly[hour]
    return overlay


def planning_flex_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """Tagesziele (kWh) für Planungs-Flex-Verbraucher im Fenster."""
    if not flex_consumers:
        return {}
    from house_config.generic_schedule import (
        generic_daily_target_kwh_for_day,
        generic_flex_target_kwh_for_window,
    )

    by_id = {consumer["id"]: consumer for consumer in _house_generic_consumers(house_profile)}
    targets: dict[str, float] = {}
    dates = {slot_dt.date() for slot_dt in slot_datetimes}
    anchor = window_end or (slot_datetimes[-1] + timedelta(hours=1) if slot_datetimes else None)
    for milp_consumer in flex_consumers:
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        if anchor is not None:
            total = generic_flex_target_kwh_for_window(source, slot_datetimes, anchor)
        else:
            total = sum(
                generic_daily_target_kwh_for_day(source, day)
                for day in dates
            )
        targets[milp_consumer["id"]] = round(total, 3)
    return targets


def profile_reference_hourly_load(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Stündlicher Referenz-Gesamtlast (kW) aus Hausprofil-Default-Schedules."""
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    flat_kw = profile_flat_baseload_kw(house_profile)
    loads: list[float] = []
    for slot_dt in slot_datetimes:
        flex_sum = sum(
            modeled_consumer_kw_at_datetime(consumer, slot_dt, climate=climate)
            for consumer in house_profile.get("consumers", [])
        )
        loads.append(round(flat_kw + flex_sum, 3))
    return loads


def tariff_reference_fingerprint(scenario_params: dict | None) -> tuple:
    """Vergleichsschlüssel für Referenz-Tarife (Import/Export)."""
    if not scenario_params:
        return ()
    import_spec = scenario_params.get("_import_tariff_spec")
    export_spec = scenario_params.get("_export_tariff_spec")
    return (
        import_spec.get("id") if isinstance(import_spec, dict) else None,
        export_spec.get("id") if isinstance(export_spec, dict) else None,
        scenario_params.get("import_tariff_type"),
        scenario_params.get("import_fixed_cent_kwh"),
        scenario_params.get("feed_in_mode"),
        scenario_params.get("k_push_cent"),
        scenario_params.get("monthly_fixed_feed_in_rates"),
    )


def resolve_profile_spec_flex_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    historical_totals: dict[str, float] | None = None,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """
    Flex-Zielenergie für profile_spec: Hausprofil-Generic + cons_data für reine Config-Verbraucher.
    """
    if not flex_consumers:
        return {}
    profile_ids = _house_profile_consumer_ids(house_profile)
    targets = planning_flex_daily_targets(
        flex_consumers,
        house_profile,
        slot_datetimes,
        window_end=window_end,
    )
    targets.update(
        planning_ev_daily_targets(
            flex_consumers,
            house_profile,
            slot_datetimes,
            window_end=window_end,
        )
    )
    cons_totals = historical_totals or {}
    for consumer in flex_consumers:
        cid = consumer["id"]
        if cid in profile_ids or cid in targets:
            continue
        targets[cid] = round(float(cons_totals.get(cid, 0.0)), 3)
    return targets


def _used_chart_color_indices(consumers: list[dict]) -> set[int]:
    used: set[int] = set()
    for consumer in consumers:
        raw = consumer.get("chart_color_index")
        if raw is None:
            continue
        try:
            used.add(int(raw))
        except (TypeError, ValueError):
            continue
    return used


def _allocate_chart_color_index(used: set[int], consumer_id: str) -> int:
    for index in range(CONSUMER_PALETTE_SIZE):
        if index not in used:
            return index
    return sum(ord(char) for char in consumer_id) % CONSUMER_PALETTE_SIZE


def merge_flexible_consumers(
    base_consumers: list[dict],
    planning_consumers: list[dict],
) -> list[dict]:
    """Config-Verbraucher + Planungs-Verbraucher ohne ID-Kollision."""
    merged = list(base_consumers)
    taken = {consumer["id"] for consumer in base_consumers}
    used_indices = _used_chart_color_indices(base_consumers)
    for consumer in planning_consumers:
        if consumer["id"] in taken:
            continue
        entry = dict(consumer)
        if entry.get("chart_color_index") is None:
            index = _allocate_chart_color_index(used_indices, str(entry["id"]))
            entry["chart_color_index"] = index
            used_indices.add(index)
        merged.append(entry)
        taken.add(entry["id"])
    return merged
