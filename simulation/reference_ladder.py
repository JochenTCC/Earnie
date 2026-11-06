"""SE reference ladder on one SoC chain: L1 = vendor-mode battery, flex at real timing;
L2 = L1 plus the standard rules moving the flex energy.

Spec: ``docs/dev/rule-based-reference.md`` §§ 2, 3, 4. Both run on the windows, targets
and flex windows of the optimized run and always book actual prices.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

import pandas as pd

from optimizer.charging_schedule import contexts_within_book
from optimizer.consumer_power import power_limits_kw
from optimizer.export_power_limit import clip_grid_kw_to_export_cap
from optimizer.milp_consumer_delivery import consumer_delivery_eligible_indices
from optimizer.milp_inputs import _resolve_thermal_flex_contexts
from optimizer.scenario_planning_scope import planning_scenario_scope
from optimizer.sim_baseline import (
    _baseline_battery_params,
    _simulate_single_hour_baseline,
    DEFAULT_RULE_PARAMS,
    SurplusRod,
    build_rule_based_flex_kw_per_hour,
    build_shaped_flex_kw_per_slot,
)
from optimizer.sim_chart_rows import COL_EINSPEISEVERGUETUNG
from optimizer.sim_costs import calculate_step_cost_parts_from_row
from optimizer.sim_horizon_types import _HorizonOptions
from optimizer.thermal_flex_context import (
    consumer_thermal_eligible_indices,
    is_heating_rod_consumer,
    is_thermal_flex_consumer,
)
from simulation.historical_cache import HistoricalDataCache
from simulation.horizon_mode import BACKTESTING_STEP_HOURS, SUNRISE_WINDOW, parse_horizon_mode
from simulation.plausibility import PlausibilityReport, validate_window_consumption
from simulation.reference_costs import (
    LADDER_L1,
    LADDER_L2,
    LADDER_STEPS,
    RUN_END_SOC_ATTR,
    _REFERENCE_COST_COLUMNS,
    _empty_reference_series,
    ladder_reference_id,
)

L1_STEUERBEFEHL = "Referenz L1"
L2_STEUERBEFEHL = "Referenz L2"
# ``run_simulation``'s default start SoC: every SE run starts there.
SE_START_SOC_PERCENT = 50.0
P_REF_IMPORT_WEIGHTED = "import_weighted"
P_REF_TIME_MEAN = "time_mean"
_LADDER_LABELS = {
    LADDER_L1: "Wechselrichter-Eigenverbrauch",
    LADDER_L2: "Standard-Regeln",
}


@dataclass(frozen=True)
class LadderReferenceResult:
    """One ladder step over the period.

    ``frame``: ``_REFERENCE_COST_COLUMNS`` plus ``sim_soc`` (start of slot). ``end_soc``: SoC
    after the last slot. ``no_shape_windows``: per consumer, the windows without a shape.
    ``no_published_block_windows``, ``truncated_lock_slots``: L2 only, see ``RuleBasedFlex``.
    """

    frame: pd.DataFrame
    plausibility: PlausibilityReport
    end_soc: float
    no_shape_windows: dict[str, int]
    no_published_block_windows: dict[str, int]
    truncated_lock_slots: int

    def report(self) -> dict:
        """What the run log keeps of a ladder run."""
        return {
            "plausibility_failed_windows": len(self.plausibility.failed),
            "no_shape_windows": self.no_shape_windows,
            "no_published_block_windows": self.no_published_block_windows,
            "truncated_lock_slots": self.truncated_lock_slots,
        }


class _WindowResult(NamedTuple):
    rows: list[dict]
    meta: dict
    end_soc: float
    no_shape_ids: list[str]
    no_published_block_ids: list[str]
    truncated_lock_slots: int


class LadderReferenceSpec(NamedTuple):
    """One L1 or L2 run of a run plan."""

    ref_id: str
    params: dict
    label: str
    step: str


@dataclass(frozen=True)
class _ShapeSource:
    """Where a run reads consumer shapes from, resolved once per run."""

    cache: HistoricalDataCache
    profile_consumers: dict[str, dict]
    climate: object | None


def _shape_source(cache: HistoricalDataCache, scenario_params: dict) -> _ShapeSource:
    from data.modeled_climate import ModeledClimateContext
    from house_config.planning_flex_bridge import PROFILE_SPEC, resolve_consumption_source

    if resolve_consumption_source(scenario_params) != PROFILE_SPEC:
        return _ShapeSource(cache, {}, None)
    profile = scenario_params["_house_profile"]
    return _ShapeSource(
        cache,
        {str(c["id"]): c for c in profile.get("consumers", []) if c.get("id")},
        ModeledClimateContext.from_scenario(scenario_params),
    )


def reference_flex_shapes_kw(
    slot_datetimes: list[datetime],
    consumers: list[dict],
    source: _ShapeSource,
) -> dict[str, list[float]]:
    """Real timing per consumer: the profile model (source of the L0 load), else cons_data."""
    from data.consumption_profiles import modeled_consumer_kw_for_slots

    shapes: dict[str, list[float]] = {}
    from_cons_data: list[str] = []
    for consumer in consumers:
        cid = str(consumer["id"])
        profile_consumer = source.profile_consumers.get(cid)
        if profile_consumer is not None:
            shapes[cid] = modeled_consumer_kw_for_slots(
                profile_consumer, slot_datetimes, climate=source.climate
            )
        else:
            from_cons_data.append(cid)
    if from_cons_data:
        shapes.update(source.cache.get_consumer_kw_for_slots(slot_datetimes, from_cons_data))
    return shapes


def _eligible_slots(setup, consumer: dict, book_indices: list[int]) -> list[int]:
    """The consumer's flex slots inside the book: the same windows as the MILP."""
    matrix = setup.matrix
    contexts = contexts_within_book(setup.charging_contexts or {}, book_indices)
    cid = consumer["id"]
    _, eligible = consumer_delivery_eligible_indices(
        matrix,
        len(matrix),
        consumer,
        book_indices,
        contexts.get(cid),
        (setup.filters or {}).get(cid),
    )
    if is_thermal_flex_consumer(consumer) or is_heating_rod_consumer(consumer):
        return consumer_thermal_eligible_indices(matrix, consumer, eligible)
    return eligible


def _surplus_rods(setup, consumers: list[dict], book_indices: list[int]) -> list[SurplusRod]:
    """L2's heating rods with the MILP's window and day heat caps: only beside a fuel source.

    A rod beside an electric heat source stays at 0 kWh (spec § 3.1).
    """
    rods = [c for c in consumers if is_heating_rod_consumer(c) and not c["parent_heat_electric"]]
    if not rods:
        return []
    contexts = _resolve_thermal_flex_contexts(setup.matrix, rods, None)
    return [
        SurplusRod(
            cid=str(rod["id"]),
            nominal_kw=power_limits_kw(rod)[1],
            eligible=_eligible_slots(setup, rod, book_indices),
            heat_left_kwh=dict(contexts[str(rod["id"])]["daily_heat_cap_kwh"]),
        )
        for rod in rods
    ]


def _book_indices(plan) -> list[int]:
    if plan.flex_book_hours is None:
        return list(range(len(plan.matrix)))
    return list(range(plan.flex_book_start, plan.flex_book_start + plan.flex_book_hours))


def _window_rows(
    anchor: datetime,
    sim_soc: float,
    *,
    scenario_params: dict,
    consumers: list[dict],
    battery_params: dict | list[dict],
    feed_in_settings,
    prices_df: pd.DataFrame,
    horizon_mode: str,
    shape_source: _ShapeSource,
    rule_params: dict | None,
) -> _WindowResult:
    from optimizer.simulation import _prepare_horizon_state
    from simulation.anchor_step import _build_anchor_window_plan

    with planning_scenario_scope(scenario_params):
        plan = _build_anchor_window_plan(
            anchor,
            sim_soc,
            horizon_mode=horizon_mode,
            cache=shape_source.cache,
            prices_df=prices_df,
            scenario_params=scenario_params,
            feed_in_settings=feed_in_settings,
            price_resources=None,
        )
        # The MILP's own preparation: its targets (fixed load credited) and flex windows.
        setup = _prepare_horizon_state(
            plan.matrix,
            sim_soc,
            _HorizonOptions(
                k_push=None,
                verbose=False,
                commit_hours=1,
                flex_book_hours=plan.flex_book_hours,
                flex_book_start=plan.flex_book_start,
                sunrise_soc_min_index=None,
                soc_hold_index=None,
                soc_hold_percent=None,
            ),
            battery_params=battery_params,
            consumer_daily_targets_kwh=plan.meta["consumer_daily_targets_kwh"],
            charging_contexts=None,
            filter_contexts=None,
            matrix_prepared=False,
            disable_horizon_soc_anchor=True,
            flexible_consumers=consumers,
        )
        book = _book_indices(plan)
        planned = [c for c in consumers if not is_heating_rod_consumer(c)]
        shapes = reference_flex_shapes_kw(
            [row["slot_datetime"] for row in setup.matrix], planned, shape_source
        )
        eligible = {c["id"]: _eligible_slots(setup, c, book) for c in planned}
        battery = _baseline_battery_params(battery_params)
        if rule_params is None:
            flex = build_shaped_flex_kw_per_slot(
                len(setup.matrix), planned, setup.horizon_limits, shapes, eligible
            )
            steuerbefehl = L1_STEUERBEFEHL
            no_published_block_ids: list[str] = []
            truncated_lock_slots = 0
        else:
            flex = build_rule_based_flex_kw_per_hour(
                setup.matrix,
                setup.horizon_limits,
                eligible,
                planned,
                shapes,
                _end_customer_price_series(
                    setup.matrix[book[0]]["slot_datetime"],
                    setup.matrix[book[-1]]["slot_datetime"],
                    prices_df,
                    scenario_params,
                ),
                rule_params,
                book_indices=book,
                battery_params=battery,
                initial_soc=sim_soc,
                surplus_rods=_surplus_rods(setup, consumers, book),
            )
            steuerbefehl = L2_STEUERBEFEHL
            no_published_block_ids = flex.no_published_block_ids
            truncated_lock_slots = flex.truncated_lock_slots
        rows: list[dict] = []
        soc = float(sim_soc)
        for t in book:
            flex_kw = {str(c["id"]): 0.0 for c in consumers} | flex.per_slot[t]
            soc, row = _simulate_single_hour_baseline(
                setup.matrix[t],
                soc,
                battery,
                flex_kw_override=flex_kw,
                steuerbefehl=steuerbefehl,
                consumers=consumers,
            )
            if rule_params is not None:
                curtail_negative_export(row, setup.matrix[t])
            rows.append(row)
    return _WindowResult(
        rows,
        plan.meta,
        soc,
        flex.no_shape_ids,
        no_published_block_ids,
        truncated_lock_slots,
    )


def curtail_negative_export(chart_row: dict, matrix_row: dict) -> None:
    """L2 limits export to zero while feeding in costs money; L1 does not (spec § 4.6)."""
    chart_row["Netzbezug (kW)"] = round(
        clip_grid_kw_to_export_cap(chart_row["Netzbezug (kW)"], k_push_act=matrix_row["k_push_act"]), 2
    )


def _end_customer_price_series(
    first_slot: datetime,
    last_slot: datetime,
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> dict[datetime, float]:
    """End-customer price per slot, from the book's start to the last day published in it.

    ``epex_prices_for_slots`` fills gaps with the previous price; here a slot without a
    market price raises, since the lock must not rank prices that did not exist. Only the
    end of the market data cuts the series, and never inside the book (spec § 4.2).
    """
    from data.backtesting_prices import (
        last_day_ahead_calendar_date,
        matrix_prices_from_context,
        pricing_kwargs_from_resolved,
    )
    from optimizer.sim_baseline import _is_nonexistent_local_slot
    from optimizer.slot_duration import DEFAULT_DT_H

    stop = datetime.combine(
        last_day_ahead_calendar_date(last_slot) + timedelta(days=1), datetime.min.time()
    )
    step = timedelta(hours=float(DEFAULT_DT_H))
    slots: list[datetime] = []
    current = first_slot
    while current < stop:
        if not _is_nonexistent_local_slot(current):
            slots.append(current)
        current += step
    index = prices_df.index
    known = index.tz_localize(None) if index.tz is not None else index
    stamps = pd.DatetimeIndex(slots)
    # Quarter-hour slots of an hourly series take the hour's price.
    has_price = stamps.isin(known) | stamps.floor("h").isin(known)
    last_priced = int(has_price.nonzero()[0].max()) if has_price.any() else -1
    gaps = stamps[: last_priced + 1][~has_price[: last_priced + 1]]
    if len(gaps):
        raise ValueError(
            f"Referenz-Regeln: Kein Börsenpreis für {gaps[0]:%Y-%m-%d %H:%M} "
            f"(die Preissperre braucht Preise bis {stop:%Y-%m-%d %H:%M})."
        )
    if last_priced < 0 or slots[last_priced] < last_slot:
        raise ValueError(
            f"Referenz-Regeln: Die Börsenpreise enden vor dem letzten gebuchten Slot "
            f"{last_slot:%Y-%m-%d %H:%M}."
        )
    slots = slots[: last_priced + 1]
    _, end_customer, _ = matrix_prices_from_context(
        prices_df, slots, None, **pricing_kwargs_from_resolved(scenario_params)
    )
    return dict(zip(slots, end_customer))


def compute_l1_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    *,
    initial_soc: float,
    horizon_mode: str,
    on_progress=None,
) -> LadderReferenceResult:
    """L1 over the period, same anchors and same start SoC as the optimized run."""
    return _compute_ladder_step(
        start,
        end,
        scenario_params,
        prices_df,
        cache,
        initial_soc=initial_soc,
        horizon_mode=horizon_mode,
        rule_params=None,
        on_progress=on_progress,
    )


def compute_l2_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    *,
    initial_soc: float,
    horizon_mode: str,
    rule_params: dict = DEFAULT_RULE_PARAMS,
    on_progress=None,
) -> LadderReferenceResult:
    """L2 over the period: L1 with the standard rules moving the flex energy (spec § 4)."""
    return _compute_ladder_step(
        start,
        end,
        scenario_params,
        prices_df,
        cache,
        initial_soc=initial_soc,
        horizon_mode=horizon_mode,
        rule_params=rule_params,
        on_progress=on_progress,
    )


def compute_ladder_reference(
    step: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    *,
    horizon_mode: str,
    on_progress=None,
) -> LadderReferenceResult:
    """One ladder step of an SE run, from the start SoC of the optimized run."""
    if step not in LADDER_STEPS:
        raise ValueError(f"Unbekannte Referenz-Stufe {step!r}.")
    compute = compute_l1_reference_costs if step == LADDER_L1 else compute_l2_reference_costs
    return compute(
        start,
        end,
        scenario_params,
        prices_df,
        cache,
        initial_soc=SE_START_SOC_PERCENT,
        horizon_mode=horizon_mode,
        on_progress=on_progress,
    )


def plan_ladder_reference_tasks(
    scenarios: dict[str, dict],
    *,
    scenario_labels: dict[str, str] | None = None,
) -> tuple[dict[str, dict[str, str]], list[LadderReferenceSpec]]:
    """L1 and L2 runs per scenario; identical setups share them (``ladder_reference_fingerprint``).

    Returns ``ladder_by_scenario`` (scenario id → step → result id) and the runs to compute.
    """
    labels = scenario_labels or {}
    ladder_by_scenario: dict[str, dict[str, str]] = {}
    specs: list[LadderReferenceSpec] = []
    owner_by_fingerprint: dict[tuple, str] = {}
    for scenario_id, params in scenarios.items():
        fingerprint = ladder_reference_fingerprint(params)
        owner = owner_by_fingerprint.get(fingerprint)
        if owner is None:
            owner = owner_by_fingerprint[fingerprint] = scenario_id
            display = labels.get(scenario_id, scenario_id)
            specs.extend(
                LadderReferenceSpec(
                    ladder_reference_id(step, scenario_id),
                    params,
                    f"{_LADDER_LABELS[step]} ({display})",
                    step,
                )
                for step in LADDER_STEPS
            )
        ladder_by_scenario[scenario_id] = {
            step: ladder_reference_id(step, owner) for step in LADDER_STEPS
        }
    return ladder_by_scenario, specs


def _compute_ladder_step(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    *,
    initial_soc: float,
    horizon_mode: str,
    rule_params: dict | None,
    on_progress=None,
) -> LadderReferenceResult:
    import config
    from simulation.engine import (
        list_simulation_anchors,
        list_sunrise_step_anchors,
    )
    from simulation.engine_scenario import (
        _consumption_kw_columns_from_chart_rows,
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
        scenario_standby_power_kw,
    )

    horizon_mode = parse_horizon_mode(horizon_mode)
    cache.load()
    anchors = (
        list_sunrise_step_anchors(start, end, cache, scenario_params)
        if horizon_mode == SUNRISE_WINDOW
        else list_simulation_anchors(start, end, cache)
    )
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )
    consumers = _flexible_consumers_from_scenario(scenario_params)
    battery_params = _scenario_to_battery_params(scenario_params)
    feed_in_settings = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    standby_kw = scenario_standby_power_kw(scenario_params)
    shape_source = _shape_source(cache, scenario_params)

    series = _empty_reference_series()
    series["sim_soc"] = []
    series["batt_action_kw"] = []
    per_consumer: dict[str, list[float]] = {}
    timestamps: list[datetime] = []
    plausibility = PlausibilityReport()
    no_shape_windows: dict[str, int] = {}
    no_published_block_windows: dict[str, int] = {}
    truncated_lock_slots = 0
    total_hours = len(anchors) * BACKTESTING_STEP_HOURS
    soc = float(initial_soc)
    for window_index, anchor in enumerate(anchors, start=1):
        window = _window_rows(
            anchor,
            soc,
            scenario_params=scenario_params,
            consumers=consumers,
            battery_params=battery_params,
            feed_in_settings=feed_in_settings,
            prices_df=prices_df,
            horizon_mode=horizon_mode,
            shape_source=shape_source,
            rule_params=rule_params,
        )
        soc = window.end_soc
        meta = window.meta
        meta["standby_power_kw"] = standby_kw
        meta["reference_no_shape_consumers"] = window.no_shape_ids
        plausibility.add(validate_window_consumption(window.rows, meta))
        for cid in window.no_shape_ids:
            no_shape_windows[cid] = no_shape_windows.get(cid, 0) + 1
        for cid in window.no_published_block_ids:
            no_published_block_windows[cid] = no_published_block_windows.get(cid, 0) + 1
        truncated_lock_slots += window.truncated_lock_slots
        for row in window.rows:
            _append_ladder_slot(series, row)
            timestamps.append(row["slot_datetime"])
        # Same per-consumer columns as an optimized run, for the SE window view.
        columns = _consumption_kw_columns_from_chart_rows(window.rows, consumers)
        for name, values in columns.items():
            if name != "consumption_kw":
                per_consumer.setdefault(name, []).extend(values)
        if on_progress is not None:
            on_progress(window_index * BACKTESTING_STEP_HOURS, total_hours)

    frame = pd.DataFrame(
        {
            **{name: series[name] for name in (*_REFERENCE_COST_COLUMNS, "sim_soc", "batt_action_kw")},
            **per_consumer,
        },
        index=pd.DatetimeIndex(timestamps),
    )
    frame.index.name = "ts"
    frame.attrs[RUN_END_SOC_ATTR] = soc
    return LadderReferenceResult(
        frame,
        plausibility,
        soc,
        no_shape_windows,
        no_published_block_windows,
        truncated_lock_slots,
    )


def _append_ladder_slot(series: dict[str, list[float]], row: dict) -> None:
    from optimizer.sim_chart_rows import flexible_consumer_power_kw

    import_eur, export_eur, net_eur, import_kwh, export_kwh = (
        calculate_step_cost_parts_from_row(row)
    )
    series["sim_cost"].append(net_eur)
    series["import_cost_eur"].append(import_eur)
    series["export_earn_eur"].append(export_eur)
    series["import_kwh"].append(import_kwh)
    series["export_kwh"].append(export_kwh)
    series["consumption_kw"].append(
        float(row["Verbrauch-Prognose (kW)"]) + flexible_consumer_power_kw(row)
    )
    series["k_act"].append(float(row["Strompreis (Cent/kWh)"]))
    series["k_push_act"].append(float(row[COL_EINSPEISEVERGUETUNG]))
    series["sim_soc"].append(float(row["Simulierter SoC (%)"]))
    series["batt_action_kw"].append(float(row["Geplante Batterie-Aktion (kW)"]))


def soc_kwh_per_percent(scenario_params: dict) -> float:
    """Usable energy of one SoC percent, as the ledger's correction counts it."""
    from simulation.engine_scenario import _scenario_to_battery_params

    battery = _baseline_battery_params(_scenario_to_battery_params(scenario_params))
    return float(battery["battery_capacity_kwh"]) * float(battery["efficiency"]) / 100.0


def soc_correction_eur(
    l3_soc: float, step_soc: float, kwh_per_percent: float, p_ref_cent: float
) -> float:
    """Positive when L3 ends fuller than the step: the step's cost is that much too low."""
    return (l3_soc - step_soc) * kwh_per_percent * p_ref_cent / 100.0


def rule_share(l0_eur: float, l2_eur: float, l3_eur: float) -> float | None:
    """Share of the rules in the total saving; ``None`` when Earnie saves nothing against L0."""
    total_saving = l0_eur - l3_eur
    return (l0_eur - l2_eur) / total_saving if total_saving > 0 else None


def period_end_exclusive(period_end: pd.Timestamp | str) -> pd.Timestamp:
    return pd.Timestamp(period_end).normalize() + pd.Timedelta(days=1)


def soc_at_period_end(frame: pd.DataFrame, end_exclusive: pd.Timestamp) -> float:
    """SoC where the booked period ends: the next slot's start SoC, else the run's end SoC."""
    index = pd.DatetimeIndex(frame.index)
    later = frame.loc[index >= end_exclusive]
    if not later.empty:
        return float(later.iloc[0]["sim_soc"])
    if RUN_END_SOC_ATTR not in frame.attrs:
        raise ValueError(f"Lauf ohne End-SoC, Periodenende {end_exclusive:%Y-%m-%d} nicht bewertbar.")
    return float(frame.attrs[RUN_END_SOC_ATTR])


def _reference_buy_price_cent(l3_frame: pd.DataFrame, end_exclusive: pd.Timestamp) -> tuple[float, str]:
    """``p_ref``: L3's import-weighted buy price of the period's last day, as the ledger does.

    A day without import takes the time mean, as an explicit rule (``savings-ledger.md`` § 3).
    """
    index = pd.DatetimeIndex(l3_frame.index)
    day = l3_frame.loc[(index >= end_exclusive - pd.Timedelta(days=1)) & (index < end_exclusive)]
    if day.empty:
        raise ValueError(f"Keine gebuchten Slots am letzten Tag vor {end_exclusive:%Y-%m-%d}.")
    import_kwh = float(day["import_kwh"].sum())
    if import_kwh > 0.0:
        return float((day["import_kwh"] * day["k_act"]).sum()) / import_kwh, P_REF_IMPORT_WEIGHTED
    return float(day["k_act"].mean()), P_REF_TIME_MEAN


def ladder_soc_correction(
    results: dict[str, pd.DataFrame],
    scenario_id: str,
    steps: dict[str, str],
    scenario_params: dict,
    period_end: pd.Timestamp | str,
) -> dict:
    """Value each step's end-of-period SoC difference to L3 (spec § 3.3, ledger formula).

    ``correction_eur`` is positive when L3 ends fuller than the step: the step's cost is
    that much too low for the comparison. ``results`` are not clipped to the period, since
    the SoC at the period's end is the start SoC of the slot behind it.
    """
    end_exclusive = period_end_exclusive(period_end)
    kwh_per_percent = soc_kwh_per_percent(scenario_params)
    l3_frame = results[scenario_id]
    l3_soc = soc_at_period_end(l3_frame, end_exclusive)
    p_ref_cent, basis = _reference_buy_price_cent(l3_frame, end_exclusive)
    block: dict = {
        "soc_end_percent": l3_soc,
        "p_ref_cent": p_ref_cent,
        "p_ref_basis": basis,
        "steps": {},
    }
    for step, ref_id in steps.items():
        step_soc = soc_at_period_end(results[ref_id], end_exclusive)
        block["steps"][step] = {
            "soc_end_percent": step_soc,
            "correction_eur": soc_correction_eur(l3_soc, step_soc, kwh_per_percent, p_ref_cent),
        }
    return block


def ladder_reference_fingerprint(scenario_params: dict) -> tuple:
    """Sharing key of L1 / L2 runs: L0's key plus the house, the battery and the flex consumers.

    L0 ignores storage and flex, so ``reference_fingerprint`` stays as it is; L1 and L2
    depend on them and may only be shared between identical setups.
    """
    from house_config.planning_flex_bridge import reference_fingerprint
    from simulation.engine_scenario import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
    )

    def canonical(value) -> str:
        return json.dumps(value, sort_keys=True, default=str)

    return (
        reference_fingerprint(scenario_params),
        canonical(scenario_params.get("_house_profile")),
        canonical(_scenario_to_battery_params(scenario_params)),
        canonical(_flexible_consumers_from_scenario(scenario_params)),
    )
