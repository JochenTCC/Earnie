"""Historical and per-scenario reference cost computation."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import config
from data import feed_in_prices
from data.market_prices import epex_prices_for_slots
from optimizer.slot_duration import wall_hours_from_slots
from simulation.historical_cache import HistoricalDataCache
from simulation.horizon_mode import BACKTESTING_STEP_HOURS


HISTORICAL_REFERENCE_ID = "historical_reference"
SCENARIO_REFERENCE_PREFIX = "ref:"


def scenario_reference_id(scenario_id: str) -> str:
    """Eindeutige Referenz-Spalte je Szenario (eigene Tarife)."""
    return f"{SCENARIO_REFERENCE_PREFIX}{scenario_id}"


def scenario_reference_label(scenario_display: str) -> str:
    """UI-Label für Szenario-Referenzkosten (ohne Batterie/Flex-Optimierung)."""
    return f"Referenz ({scenario_display}) — ohne Optimierung"


def is_scenario_reference_id(result_id: str) -> bool:
    return str(result_id).startswith(SCENARIO_REFERENCE_PREFIX)


def resolve_reference_hourly_load(
    cache: HistoricalDataCache,
    slot_datetimes: list[datetime],
    *,
    scenario_params: dict | None = None,
) -> list[float]:
    """Referenz-Gesamtlast (kW) je Slot: Hausprofil-Default oder cons_data."""
    from house_config.planning_flex_bridge import (
        PROFILE_SPEC,
        profile_reference_hourly_load,
        resolve_consumption_source,
    )

    source = resolve_consumption_source(scenario_params)
    profile = (scenario_params or {}).get("_house_profile")
    if source == PROFILE_SPEC and profile:
        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.from_scenario(scenario_params)
        return profile_reference_hourly_load(
            profile, slot_datetimes, climate=climate
        )
    _, _, total_load, _ = cache.get_window_consumption(slot_datetimes)
    return total_load


def compute_historical_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices_df: pd.DataFrame,
    feed_in_settings: feed_in_prices.FeedInSettings,
    cache: HistoricalDataCache | None = None,
    *,
    scenario_params: dict | None = None,
    on_progress=None,
) -> pd.DataFrame:
    """
    Referenzkosten: Referenz-Verbrauch + Szenario-PV, verrechnet mit Szenario-Tarifen,
    ohne Batterie- oder Flex-Optimierung (PV aus scenario_params, ggf. 0).
    """
    cache = cache or HistoricalDataCache()
    cache.load()

    from simulation.engine import (
        list_simulation_anchors,
        window_slot_datetimes,
        _brutto_prices_for_slots,
        _hour_cost_parts_without_optimization,
    )
    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    timestamps: list[datetime] = []
    costs: list[float] = []
    import_costs: list[float] = []
    export_earns: list[float] = []
    import_kwhs: list[float] = []
    export_kwhs: list[float] = []
    consumption_kws: list[float] = []
    k_act_values: list[float] = []
    k_push_values: list[float] = []
    ref_settings = feed_in_settings
    if scenario_params is not None:
        ref_settings = config.get_backtesting_feed_in_settings(
            runtime_override=scenario_params
        )

    total_hours = len(anchors) * BACKTESTING_STEP_HOURS
    hours_done = 0
    for anchor in anchors:
        slot_datetimes = window_slot_datetimes(anchor)
        total_load = resolve_reference_hourly_load(
            cache,
            slot_datetimes,
            scenario_params=scenario_params,
        )
        pv_profile = cache.get_pv_for_slots(
            slot_datetimes,
            scenario_params=scenario_params,
        )
        brutto_prices = _brutto_prices_for_slots(
            prices_df,
            slot_datetimes,
            scenario_params=scenario_params,
        )
        epex_prices = epex_prices_for_slots(prices_df, slot_datetimes)

        for slot_dt, load, pv, price, epex in zip(
            slot_datetimes, total_load, pv_profile, brutto_prices, epex_prices
        ):
            timestamps.append(slot_dt)
            k_push = feed_in_prices.resolve_k_push_act(
                epex, ref_settings, slot_datetime=slot_dt
            )
            import_eur, export_eur, net_eur, import_kwh, export_kwh = (
                _hour_cost_parts_without_optimization(load, pv, price, k_push)
            )
            costs.append(net_eur)
            import_costs.append(import_eur)
            export_earns.append(export_eur)
            import_kwhs.append(import_kwh)
            export_kwhs.append(export_kwh)
            consumption_kws.append(float(load))
            k_act_values.append(float(price))
            k_push_values.append(float(k_push))
            hours_done += 1
            if on_progress is not None:
                on_progress(wall_hours_from_slots(hours_done), total_hours)

    df_res = pd.DataFrame(
        {
            "sim_cost": costs,
            "import_cost_eur": import_costs,
            "export_earn_eur": export_earns,
            "import_kwh": import_kwhs,
            "export_kwh": export_kwhs,
            "consumption_kw": consumption_kws,
            "k_act": k_act_values,
            "k_push_act": k_push_values,
        },
        index=pd.DatetimeIndex(timestamps),
    )
    df_res.index.name = "ts"
    return df_res


def default_own_reference(
    scenario_id: str,
    params: dict,
    *,
    live_scenario_id: str,
    live_params: dict | None,
) -> bool:
    """
    Auto heuristic for ``own_reference`` when the JSON key is absent.

    True when this scenario would allocate its own ``ref:<id>`` job under the
    tariff+pv_kwp fingerprint rules (Live itself with non-baseline fingerprint;
    or a fingerprint distinct from Live and Historisch).
    """
    from house_config.entity_resolution import strip_assets_for_reference
    from house_config.planning_flex_bridge import reference_fingerprint

    if live_params is None:
        return False
    live_id = str(live_scenario_id or "").strip()
    sid = str(scenario_id or "").strip()
    baseline_fp = reference_fingerprint(strip_assets_for_reference(live_params))
    live_fp = reference_fingerprint(live_params)
    fp = reference_fingerprint(params)
    if fp == baseline_fp:
        return False
    if fp == live_fp:
        return bool(live_id) and sid == live_id
    return True


def _ensure_live_ref_spec(
    *,
    live_ref_id: str | None,
    live_scenario_id: str,
    live_params: dict | None,
    labels: dict[str, str],
    extra_labels: dict[str, str],
    extra_specs: list[tuple[str, dict, str]],
    live_ref_registered: bool,
) -> bool:
    if live_ref_registered or not live_ref_id or live_params is None:
        return live_ref_registered
    display = labels.get(live_scenario_id, live_scenario_id)
    extra_labels[live_ref_id] = scenario_reference_label(display)
    extra_specs.append((live_ref_id, dict(live_params), extra_labels[live_ref_id]))
    return True


def plan_per_scenario_reference_tasks(
    scenarios: dict[str, dict],
    *,
    live_scenario_id: str,
    scenario_labels: dict[str, str] | None = None,
    own_reference_by_scenario: dict[str, bool | None] | None = None,
) -> tuple[dict[str, str], dict[str, str], list[tuple[str, dict, str]]]:
    """
    Plant Szenario-Referenzen ohne Simulation.

    ``own_reference_by_scenario``: True/False override, None/missing = Auto
    (see ``default_own_reference``).

    Returns:
        reference_by_scenario, extra_labels, extra_specs
        extra_specs: [(ref_id, scenario_params, display_label), ...]
    """
    from house_config.entity_resolution import strip_assets_for_reference
    from house_config.planning_flex_bridge import reference_fingerprint

    labels = scenario_labels or {}
    flags = own_reference_by_scenario or {}
    live_params = scenarios.get(live_scenario_id)
    if live_params is None and scenarios:
        live_params = next(iter(scenarios.values()))
    baseline_params = (
        strip_assets_for_reference(live_params) if live_params is not None else None
    )
    baseline_fp = reference_fingerprint(baseline_params)
    live_fp = reference_fingerprint(live_params) if live_params is not None else ()
    live_ref_id = (
        scenario_reference_id(live_scenario_id) if live_scenario_id else None
    )
    live_ref_registered = False

    reference_by_scenario: dict[str, str] = {}
    extra_labels: dict[str, str] = {}
    extra_specs: list[tuple[str, dict, str]] = []
    fp_to_ref_id: dict[tuple, str] = {}

    for scenario_id, params in scenarios.items():
        fp = reference_fingerprint(params)
        if fp == baseline_fp:
            reference_by_scenario[scenario_id] = HISTORICAL_REFERENCE_ID
            continue

        explicit = flags.get(scenario_id)
        if explicit is None:
            want_own = default_own_reference(
                scenario_id,
                params,
                live_scenario_id=live_scenario_id,
                live_params=live_params,
            )
            use_dedupe = True
        else:
            want_own = bool(explicit)
            use_dedupe = False

        if not want_own:
            if live_ref_id and live_fp != baseline_fp:
                reference_by_scenario[scenario_id] = live_ref_id
                live_ref_registered = _ensure_live_ref_spec(
                    live_ref_id=live_ref_id,
                    live_scenario_id=live_scenario_id,
                    live_params=live_params,
                    labels=labels,
                    extra_labels=extra_labels,
                    extra_specs=extra_specs,
                    live_ref_registered=live_ref_registered,
                )
            else:
                reference_by_scenario[scenario_id] = HISTORICAL_REFERENCE_ID
            continue

        if use_dedupe and live_ref_id and fp == live_fp:
            reference_by_scenario[scenario_id] = live_ref_id
            live_ref_registered = _ensure_live_ref_spec(
                live_ref_id=live_ref_id,
                live_scenario_id=live_scenario_id,
                live_params=live_params,
                labels=labels,
                extra_labels=extra_labels,
                extra_specs=extra_specs,
                live_ref_registered=live_ref_registered,
            )
            continue

        if use_dedupe and fp in fp_to_ref_id:
            reference_by_scenario[scenario_id] = fp_to_ref_id[fp]
            continue

        ref_id = scenario_reference_id(scenario_id)
        if use_dedupe:
            fp_to_ref_id[fp] = ref_id
        elif fp not in fp_to_ref_id:
            fp_to_ref_id[fp] = ref_id
        display = labels.get(scenario_id, scenario_id)
        extra_labels[ref_id] = scenario_reference_label(display)
        extra_specs.append((ref_id, dict(params), extra_labels[ref_id]))
        reference_by_scenario[scenario_id] = ref_id
        if live_ref_id and scenario_id == live_scenario_id:
            live_ref_registered = True

    return reference_by_scenario, extra_labels, extra_specs


def build_per_scenario_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    scenarios: dict[str, dict],
    *,
    live_scenario_id: str,
    scenario_labels: dict[str, str] | None = None,
    own_reference_by_scenario: dict[str, bool | None] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, str]]:
    """
    Referenzkosten je Szenario (Tarif + PV).

    ``historical_reference`` = Live-Profil/Tarif ohne Batterie und ohne PV.
    Szenarien mit PV erhalten eine eigene Referenz-Spalte.

    Returns: (zusätzliche Referenz-DataFrames, Labels, scenario_id → reference_id)
    """
    reference_by_scenario, extra_labels, extra_specs = plan_per_scenario_reference_tasks(
        scenarios,
        live_scenario_id=live_scenario_id,
        scenario_labels=scenario_labels,
        own_reference_by_scenario=own_reference_by_scenario,
    )
    extra_results: dict[str, pd.DataFrame] = {}
    for ref_id, params, _label in extra_specs:
        ref_settings = config.get_backtesting_feed_in_settings(runtime_override=params)
        extra_results[ref_id] = compute_historical_reference_costs(
            start,
            end,
            prices_df,
            ref_settings,
            cache=cache,
            scenario_params=params,
        )

    return extra_results, extra_labels, reference_by_scenario


