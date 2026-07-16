"""Brücke Hausprofil-generic → Backtesting (fixe Blöcke + MILP-Flex)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from settings.ev_power import merge_ev_power_conversion_fields
from settings.flexible_consumers import CONSUMER_PALETTE_SIZE, normalize_legacy_id
from house_config.earnie_role import is_earnie_flex, is_earnie_known
from house_config.generic_schedule import (
    generic_daily_target_kwh_for_day,
    generic_hourly_kw_for_day,
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
    """Teilt generic-Verbraucher in bekannte (Grundlast) und MILP-flexible."""
    fixed: list[dict] = []
    flex: list[dict] = []
    for consumer in _house_generic_consumers(house_profile):
        if is_earnie_known(consumer):
            fixed.append(consumer)
        elif is_earnie_flex(consumer):
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
    """Hausprofil-EV → flexible_consumers-Shape für MILP; Live-Loxone aus Profil."""
    sched = consumer["charging_schedule"]
    min_on = max(1, int(consumer.get("min_on_quarterhours", 4) or 4))
    min_power = float(consumer.get("min_power_kw", 0.0) or 0.0)
    capacity = float(consumer["battery_capacity_kwh"])
    charging_schedule = merge_ev_power_conversion_fields(
        {
            "enabled": True,
            "forecast_when_absent": bool(sched.get("forecast_when_absent", True)),
            "target_soc_percent": float(sched.get("target_soc_percent", 100.0)),
            "charging_efficiency": float(sched.get("charging_efficiency", 0.95)),
            "weekday": dict(sched.get("weekday") or {}),
            "weekend": dict(sched.get("weekend") or {}),
            "battery_capacity_kwh": capacity,
        },
        sched,
    )
    sched_loxone = sched.get("loxone")
    if isinstance(sched_loxone, dict) and sched_loxone:
        charging_schedule["loxone"] = dict(sched_loxone)
    milp_raw = sched.get("milp")
    if isinstance(milp_raw, dict) and milp_raw:
        charging_schedule["milp"] = dict(milp_raw)
    result = {
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
        "charging_schedule": charging_schedule,
        "path_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
        "loxone_target_kwh_name": "",
        "loxone_target_hours_name": "",
    }
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        result["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        result["loxone_outputs"] = dict(loxone_outputs)
    setpoint_name = str((result.get("loxone_outputs") or {}).get("power_setpoint_name", "")).strip()
    if setpoint_name and not charging_schedule.get("milp"):
        raise ValueError(
            f"Hausprofil-EV '{consumer['id']}': charging_schedule.milp fehlt "
            "(live_modus_a_min_remaining_kwh, tie_break_on_epsilon, tie_break_time_epsilon) — "
            "Pflicht bei loxone_outputs.power_setpoint_name."
        )
    legacy_id = normalize_legacy_id(consumer, str(consumer["id"]))
    if legacy_id:
        result["legacy_id"] = legacy_id
    return result


def planning_ev_consumers(house_profile: dict) -> list[dict]:
    """EV-Verbraucher aus Hausprofil als MILP-flexible Verbraucher."""
    return [planning_ev_to_milp(consumer) for consumer in _house_ev_consumers(house_profile)]


def _house_thermal_rc_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "thermal_rc"
    ]


def _thermal_rc_params(consumer: dict) -> dict:
    nested = consumer.get("thermal_rc")
    if isinstance(nested, dict):
        return nested
    return consumer


def planning_thermal_rc_to_milp(consumer: dict) -> dict:
    """Hausprofil thermal_rc → MILP-flex mit thermal_control (Loxone via legacy overlay)."""
    rc = _thermal_rc_params(consumer)
    min_on = max(4, int(consumer.get("min_on_quarterhours", 8) or 8))
    legacy_id = str(consumer.get("legacy_id") or "").strip() or None
    entry = {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label", consumer["id"])),
        "nominal_power_kw": float(consumer.get("nominal_power_kw", 2.8) or 2.8),
        "min_on_quarterhours": min_on,
        "daily_target_kwh": 0.0,
        "daily_target_source": "thermal",
        "signal_type": "power",
        "log_signal_type": "power",
        "optimizer_enabled": True,
        "path_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
        "thermal_control": {
            "enabled": True,
            "mode": "active",
            "setpoint_c": float(rc["setpoint_c"]),
            "tolerance_c": float(rc["tolerance_c"]),
            "water_volume_liters": float(rc["water_volume_liters"]),
            "heat_loss_kw_per_k": float(rc["heat_loss_kw_per_k"]),
            "heating_efficiency": float(rc["heating_efficiency"]),
            "heating_power_threshold_kw": float(
                consumer.get("heating_power_threshold_kw", 2.0) or 2.0
            ),
            "actual_temp_step_c": float(consumer.get("actual_temp_step_c", 0.5) or 0.5),
            "loxone": {},
            "history_logs": {},
        },
    }
    heat_paths = rc.get("heat_paths")
    if isinstance(heat_paths, list) and heat_paths:
        entry["thermal_control"]["heat_paths"] = heat_paths
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        entry["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        entry["loxone_outputs"] = dict(loxone_outputs)
    profile_loxone = (consumer.get("thermal_control") or {}).get("loxone")
    if isinstance(profile_loxone, dict) and profile_loxone:
        entry["thermal_control"]["loxone"] = dict(profile_loxone)
    if legacy_id:
        entry["legacy_id"] = legacy_id
    return entry


SWIMSPA_FILTER_BRIDGE_DEFAULTS: dict = {
    "id": "swimspa_filter",
    "legacy_id": "swimspa_filter",
    "name": "SwimSpa Filter",
    "nominal_power_kw": 0.18,
    "daily_target_kwh": 0.36,
    "daily_target_source": "loxone_remaining_hours",
    "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
    "signal_type": "binary",
    "min_on_quarterhours": 2,
    "optimizer_enabled": True,
    "path_log": "",
    "loxone_outputs": {"enable_name": "Ernie_Swimspa_Filter_Freigabe"},
    "loxone_inputs": {
        "power_name": "homie_bwa_spa_filter2",
        "alternate_binary_power_name": "homie_bwa_spa_filter1",
        "signal_type": "binary",
    },
    "filter_schedule": {
        "enabled": True,
        "loxone": {
            "native_start_hour_name": "homie_bwa_spa_filter1hour",
            "native_duration_hours_name": "homie_bwa_spa_filter1durationhours",
        },
        "config_fallback": {
            "native_start_hour": 10,
            "native_duration_hours": 4.0,
        },
    },
}


def planning_filter_to_milp(bindings: dict | None = None) -> dict:
    """Bridge-only SwimSpa-Filter (kein Hausprofil-Row)."""
    entry = dict(SWIMSPA_FILTER_BRIDGE_DEFAULTS)
    if bindings:
        entry = _deep_merge_dict(entry, bindings)
    return entry


def planning_thermal_rc_consumers(house_profile: dict) -> list[dict]:
    return [planning_thermal_rc_to_milp(consumer) for consumer in _house_thermal_rc_consumers(house_profile)]


def collect_planning_flex_consumers(house_profile: dict) -> list[dict]:
    """Generic MILP-flex + EV + thermal_annual + thermal_rc (+ Filter bei thermal_rc)."""
    _fixed, flex_generic = split_planning_generic_consumers(house_profile)
    thermal_rc = planning_thermal_rc_consumers(house_profile)
    filters = [planning_filter_to_milp()] if thermal_rc else []
    return (
        flex_generic
        + planning_ev_consumers(house_profile)
        + planning_thermal_consumers(house_profile)
        + thermal_rc
        + filters
    )


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


def thermal_optimizer_flex_enabled(consumer: dict) -> bool:
    """True wenn thermal_annual über MILP statt PWM-Overlay laufen soll."""
    if consumer.get("type") != "thermal_annual":
        return False
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if nominal <= 0.0:
        return False
    if "optimizer_flex" in consumer:
        return bool(consumer["optimizer_flex"])
    return True


def planning_thermal_to_milp(consumer: dict) -> dict:
    """Hausprofil thermal_annual → MILP-binary mit HDD-Tagesziel (Thermals P1a)."""
    from house_config.thermal_labels import CONSUMER_TYPE_LABELS

    min_on = max(4, int(consumer.get("min_on_quarterhours", 4) or 4))
    nominal = float(consumer["nominal_power_kw"])
    entry: dict = {
        "id": str(consumer["id"]),
        "name": CONSUMER_TYPE_LABELS["thermal_annual"],
        "nominal_power_kw": nominal,
        "min_power_kw": nominal,
        "min_on_quarterhours": min_on,
        "max_on_quarterhours": int(consumer.get("max_on_quarterhours", 16) or 16),
        "max_pulses_per_day": int(consumer.get("max_pulses_per_day", 4) or 4),
        "daily_target_kwh": 0.0,
        "daily_target_source": "thermal_annual",
        "signal_type": "binary",
        "log_signal_type": "binary",
        "optimizer_enabled": True,
        "path_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
    }
    window = consumer.get("thermal_flex_window")
    if isinstance(window, dict) and window:
        entry["thermal_flex_window"] = dict(window)
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        entry["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        entry["loxone_outputs"] = dict(loxone_outputs)
    legacy_id = normalize_legacy_id(consumer, str(consumer["id"]))
    if legacy_id:
        entry["legacy_id"] = legacy_id
    return entry


def planning_thermal_consumers(house_profile: dict) -> list[dict]:
    return [
        planning_thermal_to_milp(consumer)
        for consumer in _house_thermal_consumers(house_profile)
        if thermal_optimizer_flex_enabled(consumer)
    ]


def planning_thermal_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, float]:
    """Horizont-Summe (kWh) für thermal_annual-Flex im Fenster."""
    from optimizer.thermal_flex_context import thermal_daily_kwh_for_date

    by_id = {
        str(consumer["id"]): consumer
        for consumer in _house_thermal_consumers(house_profile)
    }
    targets: dict[str, float] = {}
    dates = {slot_dt.date() for slot_dt in slot_datetimes}
    for milp_consumer in flex_consumers:
        if milp_consumer.get("daily_target_source") != "thermal_annual":
            continue
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        total = sum(
            thermal_daily_kwh_for_date(source, house_profile, day, climate=climate)
            for day in dates
        )
        targets[milp_consumer["id"]] = round(total, 3)
    return targets


def milp_flex_thermal_annual_ids(flex_consumers: list[dict] | None) -> set[str]:
    if not flex_consumers:
        return set()
    return {
        str(consumer["id"])
        for consumer in flex_consumers
        if consumer.get("daily_target_source") == "thermal_annual"
    }


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
    milp_flex_thermal_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Summiert kW thermischer Verbraucher (on/off bei nominal_power_kw) je Slot."""
    thermal = _house_thermal_consumers(house_profile)
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
    generic = fixed_generic_hourly_overlay(house_profile, slot_datetimes, skip_ids=skip_ids)
    thermal = thermal_hourly_overlay(
        house_profile,
        slot_datetimes,
        skip_consumer_ids=skip_ids,
        milp_flex_thermal_ids=milp_flex_thermal_ids,
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


def hardware_reference_fingerprint(scenario_params: dict | None) -> tuple:
    """Vergleichsschlüssel für Referenz-PV (Batterie spielt in Referenz-€ keine Rolle)."""
    if not scenario_params:
        return ()
    return (float(scenario_params.get("pv_kwp", 0.0) or 0.0),)


def reference_fingerprint(scenario_params: dict | None) -> tuple:
    """Tarif + PV für Zuordnung der Referenz-Spalte je Szenario."""
    return (
        tariff_reference_fingerprint(scenario_params),
        hardware_reference_fingerprint(scenario_params),
    )


def resolve_profile_spec_flex_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    historical_totals: dict[str, float] | None = None,
    window_end: datetime | None = None,
    climate: ModeledClimateContext | None = None,
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
    targets.update(
        planning_thermal_daily_targets(
            flex_consumers,
            house_profile,
            slot_datetimes,
            climate=climate,
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


# Historical Chart-1 / Sankey indices (Consumer colors P1): violet→…→orange palette.
# Used when config.json has no flexible_consumers row to overlay from.
_DEFAULT_CHART_COLOR_INDEX_BY_ID: dict[str, int] = {
    "swimspa": 0,
    "swimspa_filter": 1,
    "eauto": 2,
    "ev": 2,
    "waermepumpe": 7,
    "wp_heating": 7,
}

# Prefer violet/blue/cyan/orange over mid-palette greens (indices 3–6) for auto-assign.
_CHART_COLOR_ALLOCATION_ORDER: tuple[int, ...] = (0, 1, 2, 7, 6, 3, 5, 4)


def _allocate_chart_color_index(
    used: set[int],
    consumer_id: str,
    *,
    legacy_id: str | None = None,
) -> int:
    for key in (consumer_id, legacy_id):
        if not key:
            continue
        preferred = _DEFAULT_CHART_COLOR_INDEX_BY_ID.get(str(key))
        if preferred is not None and preferred not in used:
            return preferred
    for index in _CHART_COLOR_ALLOCATION_ORDER:
        if index not in used:
            return index
    return sum(ord(char) for char in consumer_id) % CONSUMER_PALETTE_SIZE


def _deep_merge_dict(base: dict, overlay: dict) -> dict:
    """Merge overlay onto base; nested dicts merged recursively."""
    merged = dict(base)
    for key, value in overlay.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


_LIVE_OVERLAY_KEYS = (
    "loxone_inputs",
    "loxone_outputs",
    "thermal_control",
    "filter_schedule",
    "chart_color_index",
    "path_log",
    "loxone_target_kwh_name",
    "loxone_target_hours_name",
)


def _overlay_legacy_consumer(planning: dict, base: dict) -> dict:
    """Live fields from legacy base entry onto canonical planning row."""
    entry = dict(planning)
    for key in _LIVE_OVERLAY_KEYS:
        base_val = base.get(key)
        if base_val is None:
            continue
        if key in entry and isinstance(entry.get(key), dict) and isinstance(base_val, dict):
            entry[key] = _deep_merge_dict(base_val, entry[key])
        else:
            entry[key] = base_val
    base_cs = base.get("charging_schedule") or {}
    if base_cs:
        entry_cs = dict(entry.get("charging_schedule") or {})
        base_lox = base_cs.get("loxone") or {}
        if base_lox:
            entry_cs["loxone"] = _deep_merge_dict(
                base_lox,
                entry_cs.get("loxone") or {},
            )
        for cs_key in ("enabled", "forecast_when_absent", "target_soc_percent", "charging_efficiency"):
            if cs_key in base_cs and cs_key not in entry_cs:
                entry_cs[cs_key] = base_cs[cs_key]
        for day_key in ("weekday", "weekend"):
            if base_cs.get(day_key) and not entry_cs.get(day_key):
                entry_cs[day_key] = dict(base_cs[day_key])
        entry["charging_schedule"] = _deep_merge_dict(base_cs, entry_cs)
    if entry.get("chart_color_index") is None and base.get("chart_color_index") is not None:
        entry["chart_color_index"] = base["chart_color_index"]
    return entry


def merge_flexible_consumers(
    base_consumers: list[dict],
    planning_consumers: list[dict],
) -> list[dict]:
    """Config-Verbraucher + Planungs-Verbraucher; legacy_id overlay when ids differ."""
    merged_map: dict[str, dict] = {c["id"]: dict(c) for c in base_consumers}
    used_indices = _used_chart_color_indices(list(merged_map.values()))
    for consumer in planning_consumers:
        entry = dict(consumer)
        canonical_id = str(entry["id"])
        legacy_id = str(entry.get("legacy_id") or "").strip()
        if legacy_id and legacy_id in merged_map and legacy_id != canonical_id:
            entry = _overlay_legacy_consumer(entry, merged_map[legacy_id])
            del merged_map[legacy_id]
        if canonical_id in merged_map:
            continue
        if entry.get("chart_color_index") is None:
            index = _allocate_chart_color_index(
                used_indices,
                canonical_id,
                legacy_id=legacy_id or None,
            )
            entry["chart_color_index"] = index
            used_indices.add(index)
        merged_map[canonical_id] = entry
    return list(merged_map.values())
