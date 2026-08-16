"""Baseload / thermal overlays and daily flex targets for profile_spec planning."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from house_config.consumption_csv import consumer_uses_profile_csv
from house_config.planning_flex_converters import (
    _consumer_window_kwh,
    _house_ev_consumers,
    _house_generic_consumers,
    _house_profile_consumer_ids,
    _house_thermal_consumers,
    _house_thermal_rc_consumers,
    split_planning_generic_consumers,
)
from house_config.profile_csv_policy import se_uses_meter_residual_baseload

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext


def profile_flat_baseload_kw(house_profile: dict) -> float:
    """Konstante Grundlast (kW) aus profile.baseload_kwh."""
    return float(house_profile.get("baseload_kwh", 0.0) or 0.0) / 8760.0


def monthly_residual_baseload_kw(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Path A monthly: per-month Ist − Σ model consumers, mapped onto slots.

    Months missing from Gesamt-CSV fall back to flat ``baseload_kwh/8760``.
    """
    from house_config.baseload import (
        baseload_month_key,
        monthly_baseload_kw_by_month,
    )
    from house_config.consumption_csv import load_hourly_profile_csv
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    csv_path = str(house_profile.get("total_profile_csv", "") or "").strip()
    if not csv_path:
        raise ValueError("monthly residual requires total_profile_csv")
    rows = list(load_hourly_profile_csv(csv_path))
    if not rows:
        flat = profile_flat_baseload_kw(house_profile)
        return [round(flat, 6)] * len(slot_datetimes)
    timestamps = [ts for ts, _ in rows]
    ist_kw = [float(kw) for _, kw in rows]
    consumers = list(house_profile.get("consumers", []))
    consumer_kw = [
        sum(
            float(
                modeled_consumer_kw_at_datetime(
                    consumer,
                    datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                    climate=climate,
                )
                or 0.0
            )
            for consumer in consumers
        )
        for ts in timestamps
    ]
    month_map = monthly_baseload_kw_by_month(timestamps, ist_kw, consumer_kw)
    flat = profile_flat_baseload_kw(house_profile)
    return [
        round(month_map.get(baseload_month_key(slot_dt), flat), 6)
        for slot_dt in slot_datetimes
    ]


def planning_ev_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """Window kWh for EV flex — same power-capped schedule as cons_data / Historisch.

    SOC-only ``ev_daily_kwh`` can exceed what ``nominal_power_kw`` delivers in the
    charging window; using slot-modeled energy keeps profile_spec Jahres Verbrauch
    aligned with synthetic Historisch (same pattern as thermal_annual).
    """
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
        targets[milp_consumer["id"]] = _consumer_window_kwh(source, slot_datetimes)
    return targets


def planning_thermal_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, float]:
    """Window kWh for thermal_annual flex (slot-aligned, not full calendar days).

    Sunset/24h windows often span two calendar dates. Summing
    ``thermal_daily_kwh_for_date`` per touched date roughly doubles WP energy
    vs cons_data / hourly synthesis. Always use slot-hour energy instead.
    """
    by_id = {
        str(consumer["id"]): consumer
        for consumer in _house_thermal_consumers(house_profile)
    }
    targets: dict[str, float] = {}
    for milp_consumer in flex_consumers:
        if milp_consumer.get("daily_target_source") != "thermal_annual":
            continue
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        targets[milp_consumer["id"]] = _consumer_window_kwh(
            source, slot_datetimes, climate=climate
        )
    return targets


def planning_thermal_rc_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, float]:
    """Window kWh for non-CSV thermal_rc MILP-flex (CSV thermal_rc uses overlay)."""
    by_id = {
        str(consumer["id"]): consumer
        for consumer in _house_thermal_rc_consumers(house_profile)
    }
    targets: dict[str, float] = {}
    for milp_consumer in flex_consumers:
        if milp_consumer.get("daily_target_source") != "thermal":
            continue
        source = by_id.get(str(milp_consumer["id"]))
        if not source or consumer_uses_profile_csv(source):
            continue
        targets[str(milp_consumer["id"])] = _consumer_window_kwh(
            source, slot_datetimes, climate=climate
        )
    return targets


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
    milp_flex_thermal_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Summiert kW thermischer Verbraucher je Slot (annual + CSV thermal_rc)."""
    thermal_annual = _house_thermal_consumers(house_profile)
    thermal_rc_csv = [
        consumer
        for consumer in _house_thermal_rc_consumers(house_profile)
        if consumer_uses_profile_csv(consumer)
    ]
    thermal = list(thermal_annual) + thermal_rc_csv
    if not thermal:
        return [0.0] * len(slot_datetimes)
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    skip = skip_consumer_ids or set()
    milp_skip = milp_flex_thermal_ids or set()
    active = [
        consumer
        for consumer in thermal
        if str(consumer.get("id") or "") not in skip
        and str(consumer.get("id") or "") not in milp_skip
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


def fixed_generic_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    skip_ids: set[str] | None = None,
    meter_residual_mode: bool | None = None,
) -> list[float]:
    """Summiert kW fixer generic-Verbraucher je Slot (CSV wins over schedule).

    In meter-residual mode (path B), known without CSV stay inside residual —
    do not also overlay their weekly schedule.
    """
    fixed, _flex = split_planning_generic_consumers(house_profile)
    if not fixed:
        return [0.0] * len(slot_datetimes)
    use_residual = (
        se_uses_meter_residual_baseload(house_profile)
        if meter_residual_mode is None
        else bool(meter_residual_mode)
    )
    skip = skip_ids or set()
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    overlay = [0.0] * len(slot_datetimes)
    for slot_index, slot_dt in enumerate(slot_datetimes):
        for consumer in fixed:
            cid = str(consumer.get("id") or "")
            if cid in skip:
                continue
            if use_residual and not consumer_uses_profile_csv(consumer):
                continue
            overlay[slot_index] += float(
                modeled_consumer_kw_at_datetime(consumer, slot_dt) or 0.0
            )
    return overlay


def house_profile_baseload_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    historical_totals: dict[str, float] | None = None,
    cons_data_consumer_ids: set[str] | None = None,
    milp_flex_thermal_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Fixe generic- und thermische Verbraucher aus Hausprofil je Slot."""
    skip_ids = _consumer_ids_with_cons_data(
        house_profile,
        historical_totals,
        cons_data_consumer_ids=cons_data_consumer_ids,
    )
    generic = fixed_generic_hourly_overlay(
        house_profile,
        slot_datetimes,
        skip_ids=skip_ids,
        meter_residual_mode=se_uses_meter_residual_baseload(house_profile),
    )
    thermal = thermal_hourly_overlay(
        house_profile,
        slot_datetimes,
        skip_consumer_ids=skip_ids,
        milp_flex_thermal_ids=milp_flex_thermal_ids,
        climate=climate,
    )
    return [round(g + t, 6) for g, t in zip(generic, thermal)]


def meter_residual_baseload_kw(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> tuple[list[float], int]:
    """Path B: hourly residual = total_profile_csv − Σ(accounted CSV series).

    Controllable CSVs are peeled (MILP re-adds). Known CSV peeled and re-added
    via fixed overlay. Returns (residual_kw, clipped_hours).
    """
    from house_config.consumption_csv import load_hourly_profile_csv
    from house_config.profile_csv_policy import accounted_csv_consumers
    from data.consumption_profiles import (
        csv_kw_at_datetime,
        modeled_consumer_kw_at_datetime,
    )

    csv_path = str(house_profile.get("total_profile_csv", "") or "").strip()
    if not csv_path:
        raise ValueError("meter residual requires total_profile_csv")
    lookup = {ts: float(kw) for ts, kw in load_hourly_profile_csv(csv_path)}
    accounted = accounted_csv_consumers(house_profile)
    residual: list[float] = []
    clipped = 0
    for slot_dt in slot_datetimes:
        key = slot_dt.strftime("%Y-%m-%d %H:%M:%S")
        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        total = float(lookup.get(key, lookup.get(naive.strftime("%Y-%m-%d %H:%M:%S"), 0.0)))
        peel = 0.0
        for consumer in accounted:
            if consumer_uses_profile_csv(consumer):
                peel += float(csv_kw_at_datetime(consumer["profile_csv"], slot_dt) or 0.0)
            else:
                peel += float(
                    modeled_consumer_kw_at_datetime(
                        consumer, slot_dt, climate=climate
                    )
                    or 0.0
                )
        value = total - peel
        if value < 0.0:
            clipped += 1
            value = 0.0
        residual.append(round(value, 6))
    return residual, clipped


def planning_flex_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """Tagesziele (kWh) für Planungs-Flex-Verbraucher im Fenster.

    With ``use_profile_csv``, use CSV window energy; otherwise schedule energy.
    """
    if not flex_consumers:
        return {}
    from house_config.generic_schedule import (
        generic_daily_target_kwh_for_day,
        generic_flex_target_kwh_for_window,
    )

    by_id = {consumer["id"]: consumer for consumer in _house_generic_consumers(house_profile)}
    # Also map flex/manual that only have schedule via full consumer list
    for consumer in house_profile.get("consumers", []):
        if consumer.get("type") == "generic" and consumer.get("id"):
            by_id.setdefault(consumer["id"], consumer)
    targets: dict[str, float] = {}
    dates = {slot_dt.date() for slot_dt in slot_datetimes}
    anchor = window_end or (slot_datetimes[-1] + timedelta(hours=1) if slot_datetimes else None)
    for milp_consumer in flex_consumers:
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        if consumer_uses_profile_csv(source):
            targets[milp_consumer["id"]] = _consumer_window_kwh(source, slot_datetimes)
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
    from house_config.profile_csv_policy import se_uses_monthly_baseload

    if se_uses_monthly_baseload(house_profile):
        baseload_series = monthly_residual_baseload_kw(
            house_profile,
            slot_datetimes,
            climate=climate,
        )
    else:
        flat_kw = profile_flat_baseload_kw(house_profile)
        baseload_series = [flat_kw] * len(slot_datetimes)
    loads: list[float] = []
    for slot_dt, base_kw in zip(slot_datetimes, baseload_series):
        flex_sum = sum(
            modeled_consumer_kw_at_datetime(consumer, slot_dt, climate=climate)
            for consumer in house_profile.get("consumers", [])
        )
        loads.append(round(base_kw + flex_sum, 3))
    return loads
