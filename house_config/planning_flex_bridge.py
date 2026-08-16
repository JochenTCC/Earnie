"""Brücke Hausprofil-generic → Backtesting (fixe Blöcke + MILP-Flex)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from settings.flexible_consumers import CONSUMER_PALETTE_SIZE

from house_config.planning_flex_converters import (
    POOL_FILTER_ID,
    _attach_ehal_bindings,
    _apply_live_signal_type,
    _consumer_window_kwh,
    _ensure_shared_meter_filter_subtract,
    _generic_live_signal_type,
    _house_ev_consumers,
    _house_generic_consumers,
    _house_pool_filter_consumer,
    _house_profile_consumer_ids,
    _house_thermal_consumers,
    _house_thermal_rc_consumers,
    _pool_filter_daily_target_kwh,
    _pool_filter_schedule,
    _thermal_rc_params,
    collect_planning_flex_consumers,
    is_milp_pool_filter,
    milp_flex_thermal_annual_ids,
    planning_consumer_to_milp,
    planning_ev_consumers,
    planning_ev_to_milp,
    planning_pool_filter_to_milp,
    planning_thermal_consumers,
    planning_thermal_rc_consumers,
    planning_thermal_rc_to_milp,
    planning_thermal_to_milp,
    split_planning_generic_consumers,
    thermal_optimizer_flex_enabled,
)
from house_config.planning_flex_overlays import (
    _consumer_ids_with_cons_data,
    fixed_generic_hourly_overlay,
    house_profile_baseload_overlay,
    meter_residual_baseload_kw,
    monthly_residual_baseload_kw,
    planning_ev_daily_targets,
    planning_flex_daily_targets,
    planning_thermal_daily_targets,
    planning_thermal_rc_daily_targets,
    profile_flat_baseload_kw,
    profile_reference_hourly_load,
    thermal_hourly_overlay,
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
    targets.update(
        planning_thermal_rc_daily_targets(
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
        cons_kwh = float(cons_totals.get(cid, 0.0) or 0.0)
        if cid in cons_totals and cons_kwh > 0.0:
            targets[cid] = round(cons_kwh, 3)
        else:
            targets[cid] = round(float(consumer.get("daily_target_kwh", 0.0) or 0.0), 3)
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
    "pool_filter": 1,
    "ev": 2,
    "wp_heating": 7,
}

# Prefer violet/blue/cyan/orange over mid-palette greens (indices 3–6) for auto-assign.
_CHART_COLOR_ALLOCATION_ORDER: tuple[int, ...] = (0, 1, 2, 7, 6, 3, 5, 4)


def _allocate_chart_color_index(used: set[int], consumer_id: str) -> int:
    preferred = _DEFAULT_CHART_COLOR_INDEX_BY_ID.get(str(consumer_id))
    if preferred is not None and preferred not in used:
        return preferred
    for index in _CHART_COLOR_ALLOCATION_ORDER:
        if index not in used:
            return index
    return sum(ord(char) for char in consumer_id) % CONSUMER_PALETTE_SIZE


def merge_flexible_consumers(
    base_consumers: list[dict],
    planning_consumers: list[dict],
) -> list[dict]:
    """Config-Verbraucher + Planungs-Verbraucher, zusammengeführt über die kanonische id."""
    merged_map: dict[str, dict] = {c["id"]: dict(c) for c in base_consumers}
    used_indices = _used_chart_color_indices(list(merged_map.values()))
    for consumer in planning_consumers:
        entry = dict(consumer)
        canonical_id = str(entry["id"])
        if canonical_id in merged_map:
            continue
        if entry.get("chart_color_index") is None:
            index = _allocate_chart_color_index(used_indices, canonical_id)
            entry["chart_color_index"] = index
            used_indices.add(index)
        merged_map[canonical_id] = entry
    return list(merged_map.values())


# Re-Exports für API-Stabilität (from house_config.planning_flex_bridge import ...)
__all__ = [
    "CONSUMPTION_SOURCES",
    "LOGGED_DAY",
    "POOL_FILTER_ID",
    "PROFILE_SPEC",
    "_allocate_chart_color_index",
    "_attach_ehal_bindings",
    "_apply_live_signal_type",
    "_consumer_ids_with_cons_data",
    "_consumer_window_kwh",
    "_ensure_shared_meter_filter_subtract",
    "_generic_live_signal_type",
    "_house_ev_consumers",
    "_house_generic_consumers",
    "_house_pool_filter_consumer",
    "_house_profile_consumer_ids",
    "_house_thermal_consumers",
    "_house_thermal_rc_consumers",
    "_pool_filter_daily_target_kwh",
    "_pool_filter_schedule",
    "_thermal_rc_params",
    "_used_chart_color_indices",
    "collect_planning_flex_consumers",
    "fixed_generic_hourly_overlay",
    "hardware_reference_fingerprint",
    "house_profile_baseload_overlay",
    "is_milp_pool_filter",
    "merge_flexible_consumers",
    "meter_residual_baseload_kw",
    "milp_flex_thermal_annual_ids",
    "monthly_residual_baseload_kw",
    "planning_consumer_to_milp",
    "planning_ev_consumers",
    "planning_ev_daily_targets",
    "planning_ev_to_milp",
    "planning_flex_daily_targets",
    "planning_pool_filter_to_milp",
    "planning_thermal_consumers",
    "planning_thermal_daily_targets",
    "planning_thermal_rc_consumers",
    "planning_thermal_rc_daily_targets",
    "planning_thermal_rc_to_milp",
    "planning_thermal_to_milp",
    "profile_flat_baseload_kw",
    "profile_reference_hourly_load",
    "reference_fingerprint",
    "resolve_consumption_source",
    "resolve_profile_spec_flex_targets",
    "split_planning_generic_consumers",
    "tariff_reference_fingerprint",
    "thermal_hourly_overlay",
    "thermal_optimizer_flex_enabled",
]
