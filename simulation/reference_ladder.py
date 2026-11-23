"""SE reference ladder on one SoC chain: L1 = vendor-mode battery, flex at real timing;
L2 = L1 plus the standard rules moving the flex energy.

Spec: ``docs/dev/rule-based-reference.md`` §§ 2, 3, 4. Both run on the windows, targets
and flex windows of the optimized run and always book actual prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

import pandas as pd

from optimizer.charging_schedule import contexts_within_book
from optimizer.consumer_power import power_limits_kw
from optimizer.milp_consumer_delivery import consumer_delivery_eligible_indices
from optimizer.milp_inputs import _resolve_thermal_flex_contexts
from optimizer.rod_store import ROD_STORE_START_KEY, STORE_BALANCE_CONTEXT_KEY
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
from simulation.reference_ladder_prices import (  # noqa: F401  re-exported (import facade)
    _end_customer_price_series,
    curtail_negative_export,
)
from simulation.reference_ladder_soc import (  # noqa: F401  re-exported (import facade)
    P_REF_IMPORT_WEIGHTED,
    P_REF_TIME_MEAN,
    _reference_buy_price_cent,
    ladder_reference_fingerprint,
    ladder_soc_correction,
    period_end_exclusive,
    rule_share,
    soc_at_period_end,
    soc_correction_eur,
    soc_kwh_per_percent,
)

L1_STEUERBEFEHL = "Referenz L1"
L2_STEUERBEFEHL = "Referenz L2"
# ``run_simulation``'s default start SoC: every SE run starts there.
SE_START_SOC_PERCENT = 50.0
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
    rod_store_kwh: dict[str, float]


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
    """L2's heating rods with the MILP's window and store: only beside a fuel source.

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
            balance=contexts[str(rod["id"])][STORE_BALANCE_CONTEXT_KEY],
            level_kwh=contexts[str(rod["id"])][STORE_BALANCE_CONTEXT_KEY].start_kwh,
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
    rod_store_kwh: dict[str, float],
) -> _WindowResult:
    from simulation.anchor_step import _build_anchor_window_plan

    surplus_rods: list[SurplusRod] = []
    with planning_scenario_scope({**scenario_params, ROD_STORE_START_KEY: rod_store_kwh}):
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
        setup = _milp_window_setup(plan, sim_soc, battery_params, consumers)
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
            surplus_rods = _surplus_rods(setup, consumers, book)
            flex = _rule_based_window_flex(
                setup,
                planned=planned,
                shapes=shapes,
                eligible=eligible,
                book=book,
                prices_df=prices_df,
                scenario_params=scenario_params,
                rule_params=rule_params,
                battery=battery,
                sim_soc=sim_soc,
                surplus_rods=surplus_rods,
            )
            steuerbefehl = L2_STEUERBEFEHL
            no_published_block_ids = flex.no_published_block_ids
            truncated_lock_slots = flex.truncated_lock_slots
        soc, rows = _book_window_slots(
            setup,
            book,
            flex,
            sim_soc=sim_soc,
            battery=battery,
            steuerbefehl=steuerbefehl,
            consumers=consumers,
            curtail=rule_params is not None,
        )
    return _WindowResult(
        rows,
        plan.meta,
        soc,
        flex.no_shape_ids,
        no_published_block_ids,
        truncated_lock_slots,
        {rod.cid: rod.level_kwh for rod in surplus_rods},
    )


def _milp_window_setup(plan, sim_soc: float, battery_params, consumers: list[dict]):
    """The MILP's own preparation: its targets (fixed load credited) and flex windows."""
    from optimizer.simulation import _prepare_horizon_state

    return _prepare_horizon_state(
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


def _rule_based_window_flex(
    setup,
    *,
    planned: list[dict],
    shapes: dict[str, list[float]],
    eligible: dict,
    book: list[int],
    prices_df: pd.DataFrame,
    scenario_params: dict,
    rule_params: dict,
    battery,
    sim_soc: float,
    surplus_rods: list[SurplusRod],
):
    """L2: the standard rules move the flex energy inside the book."""
    return build_rule_based_flex_kw_per_hour(
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
        surplus_rods=surplus_rods,
    )


def _book_window_slots(
    setup,
    book: list[int],
    flex,
    *,
    sim_soc: float,
    battery,
    steuerbefehl: str,
    consumers: list[dict],
    curtail: bool,
) -> tuple[float, list[dict]]:
    """Books the window's slots on the SoC chain; returns the end SoC and the chart rows."""
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
        if curtail:
            curtail_negative_export(row, setup.matrix[t])
        rows.append(row)
    return soc, rows


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
    steps: tuple[str, ...],
    scenario_labels: dict[str, str] | None = None,
) -> tuple[dict[str, dict[str, str]], list[LadderReferenceSpec]]:
    """L1 (and L2) runs per scenario; identical setups share them (``ladder_reference_fingerprint``).

    ``steps``: ``(l1,)`` for the SE box L1, ``(l1, l2)`` with the hidden switch ``rule_reference``.
    Returns ``ladder_by_scenario`` (scenario id → step → result id) and the runs to compute.
    L1 runs that differ only in the tariff are computed once more by the runner
    (``simulation.reference_dedup``); the plan keeps one result id per tariff.
    """
    unknown = [step for step in steps if step not in LADDER_STEPS]
    if unknown or not steps:
        raise ValueError(f"Unbekannte Referenz-Stufen {steps!r}.")
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
                for step in steps
            )
        ladder_by_scenario[scenario_id] = {
            step: ladder_reference_id(step, owner) for step in steps
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
    from simulation.engine_scenario import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
        scenario_standby_power_kw,
    )

    horizon_mode = parse_horizon_mode(horizon_mode)
    cache.load()
    anchors = _ladder_anchors(start, end, cache, scenario_params, horizon_mode)
    consumers = _flexible_consumers_from_scenario(scenario_params)
    battery_params = _scenario_to_battery_params(scenario_params)
    feed_in_settings = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    standby_kw = scenario_standby_power_kw(scenario_params)
    shape_source = _shape_source(cache, scenario_params)

    acc = _LadderAccumulator(consumers)
    total_hours = len(anchors) * BACKTESTING_STEP_HOURS
    soc = float(initial_soc)
    rod_store_kwh: dict[str, float] = {}
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
            rod_store_kwh=rod_store_kwh,
        )
        soc = window.end_soc
        rod_store_kwh = window.rod_store_kwh
        acc.add_window(window, standby_kw)
        if on_progress is not None:
            on_progress(window_index * BACKTESTING_STEP_HOURS, total_hours)
    return acc.result(soc)


def _ladder_anchors(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache: HistoricalDataCache,
    scenario_params: dict,
    horizon_mode: str,
) -> list:
    """The run's anchors, the same as ``run_simulation``; no window raises."""
    from simulation.engine import (
        list_simulation_anchors,
        list_sunrise_step_anchors,
    )

    anchors = (
        list_sunrise_step_anchors(start, end, cache, scenario_params)
        if horizon_mode == SUNRISE_WINDOW
        else list_simulation_anchors(start, end, cache)
    )
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )
    return anchors


class _LadderAccumulator:
    """Collects the booked windows of one ladder step into series and counters."""

    def __init__(self, consumers: list[dict]) -> None:
        self.consumers = consumers
        self.series = _empty_reference_series()
        self.series["sim_soc"] = []
        self.series["batt_action_kw"] = []
        self.per_consumer: dict[str, list[float]] = {}
        self.timestamps: list[datetime] = []
        self.plausibility = PlausibilityReport()
        self.no_shape_windows: dict[str, int] = {}
        self.no_published_block_windows: dict[str, int] = {}
        self.truncated_lock_slots = 0

    def add_window(self, window: _WindowResult, standby_kw: float) -> None:
        from simulation.engine_scenario import _consumption_kw_columns_from_chart_rows

        meta = window.meta
        meta["standby_power_kw"] = standby_kw
        meta["reference_no_shape_consumers"] = window.no_shape_ids
        self.plausibility.add(validate_window_consumption(window.rows, meta))
        for cid in window.no_shape_ids:
            self.no_shape_windows[cid] = self.no_shape_windows.get(cid, 0) + 1
        for cid in window.no_published_block_ids:
            self.no_published_block_windows[cid] = self.no_published_block_windows.get(cid, 0) + 1
        self.truncated_lock_slots += window.truncated_lock_slots
        for row in window.rows:
            _append_ladder_slot(self.series, row)
            self.timestamps.append(row["slot_datetime"])
        # Same per-consumer columns as an optimized run, for the SE window view.
        columns = _consumption_kw_columns_from_chart_rows(window.rows, self.consumers)
        for name, values in columns.items():
            if name != "consumption_kw":
                self.per_consumer.setdefault(name, []).extend(values)

    def result(self, soc: float) -> LadderReferenceResult:
        series = self.series
        frame = pd.DataFrame(
            {
                **{
                    name: series[name]
                    for name in (*_REFERENCE_COST_COLUMNS, "sim_soc", "batt_action_kw")
                },
                **self.per_consumer,
            },
            index=pd.DatetimeIndex(self.timestamps),
        )
        frame.index.name = "ts"
        frame.attrs[RUN_END_SOC_ATTR] = soc
        return LadderReferenceResult(
            frame,
            self.plausibility,
            soc,
            self.no_shape_windows,
            self.no_published_block_windows,
            self.truncated_lock_slots,
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
