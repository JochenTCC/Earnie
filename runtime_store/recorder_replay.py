"""Offline MILP replay from cycle-recorder entries (Regression R0 / P1/L3).

Replays from frozen pre-prepare inputs. The standby-backup load relief is
recomputed from the snapshot (pack, SoC, matrix) and applied before the solve,
as the live cycle does after the recorder snapshot. The sunrise PV-only charge
limit uses the recorded planning window. EHAL telemetry is not read.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Re-exported: callers and tests import these from ``runtime_store.recorder_replay``.
from runtime_store.recorder_replay_env import (  # noqa: F401
    _ARCHIVE_TO_ENV,
    _ENV_CLEAR_SUFFIXES,
    _FLAG_NAMES,
    _activate_env,
    _best_effort_rmtree,
    _coerce_matrix_datetimes,
    _drop_removed_empty_overlay,
    _entry_is_flagged,
    _entry_slot_count,
    _migrate_snapshot_config,
    _rebind_consumer_state_path,
    _restore_env,
    _segment_paths_for_root,
    _write_start_state_files,
    load_config_snapshot,
    materialize_config_snapshot,
    restore_matrix_from_entry,
)
from runtime_store.recorder_replay_inputs import (  # noqa: F401
    _aware_local,
    _battery_params_from_config,
    _battery_params_with_recorded_ess_limits,
    _battery_params_with_recorded_reserves,
    _filter_batteries_with_soc,
    _inverter_params_from_config,
    _normalize_slot,
    _pv_systems_from_config,
    _recorded_ev_limit_soc,
    _recorded_export_limits,
    _recorded_import_cap_observe,
    _recorded_import_caps,
    _recorded_planning_moment,
    _recorded_sunrise_soc_min_index,
    _recorded_thermal_readings,
    _require_push_price_cent,
)

logger = logging.getLogger(__name__)

SolverMode = Literal["production", "strict"]


@dataclass
class ReplayResult:
    """Compact metrics from one offline recorder replay."""

    n_slots: int
    seconds: float
    stage: str
    status: str
    plan_hash: str
    cost_euro: float | None
    objective_raw: float | None
    mode: int
    target_power_kw: float
    battery_plan_kw: float | None
    consumer_powers_kw: dict[str, float] = field(default_factory=dict)
    cbc_events: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str | None = None
    config_hash: str | None = None
    # One record per MILP solve of the replay (``optimizer.cbc_solver.take_solve_log``).
    solver: list[dict[str, Any]] = field(default_factory=list)
    # Import cap report of the replayed plan (``optimizer.import_cap_report``); None without a cap.
    import_cap_report: dict[str, Any] | None = None

    @property
    def time_limit_hit(self) -> bool:
        """True when a solve of the replay stopped at a time limit (plan depends on CPU speed)."""
        return any(solve_hit_time_limit(rec) for rec in self.solver)


def list_full_horizon_cycles(
    recorder_root: Path | str,
    *,
    min_slots: int = 96,
    max_cases: int | None = None,
    require_unflagged: bool = True,
) -> list[dict[str, Any]]:
    """Load recorder segments and pick cycles with at least ``min_slots`` rows."""
    from runtime_store.cycle_recorder import read_segment_cycles

    root = Path(recorder_root)
    if not root.is_dir():
        raise FileNotFoundError(f"recorder root missing: {root}")
    selected: list[dict[str, Any]] = []
    for segment in _segment_paths_for_root(root):
        for entry in read_segment_cycles(segment):
            if not _entry_slot_count(entry) >= min_slots:
                continue
            if require_unflagged and _entry_is_flagged(entry):
                continue
            selected.append(entry)
            if max_cases is not None and len(selected) >= max_cases:
                return selected
    return selected


def replay_recorded_cycle(
    entry: dict[str, Any],
    *,
    recorder_root: Path | str,
    solver_mode: SolverMode = "strict",
    env_dest: Path | str | None = None,
    verbose: bool = False,
) -> ReplayResult:
    """Materialize snapshot, prepare matrix, solve MILP, return metrics."""
    config_hash = str(entry.get("config_hash") or "")
    if not config_hash:
        raise ValueError("entry missing config_hash")
    snapshot = load_config_snapshot(recorder_root, config_hash)
    cleanup_env = False
    if env_dest is None:
        env_dest = Path(tempfile.mkdtemp(prefix="earnie_r0_replay_"))
        cleanup_env = True
    env_root = materialize_config_snapshot(snapshot, env_dest)
    _write_start_state_files(env_root, entry.get("start_state") or {})
    previous_env = _activate_env(env_root)
    try:
        return _solve_prepared_entry(
            entry,
            solver_mode=solver_mode,
            verbose=verbose,
        )
    finally:
        _restore_env(previous_env)
        if cleanup_env:
            _best_effort_rmtree(env_root)


def _solve_prepared_entry(
    entry: dict[str, Any],
    *,
    solver_mode: SolverMode,
    verbose: bool,
) -> ReplayResult:
    import config
    from optimizer.cbc_events import begin_cbc_event_collection, take_cbc_events
    from optimizer.cbc_solver import (
        apply_cbc_solver_env,
        begin_solve_log,
        clear_cbc_solver_env,
        take_solve_log,
    )

    config.reinit_config()
    clear_cbc_solver_env()
    apply_cbc_solver_env(strict=(solver_mode == "strict"))
    os.environ["EARNIE_MILP_SOLVER"] = "highs"

    from contextlib import ExitStack

    from data.outdoor_forecast import replay_outdoor_forecast
    from optimizer.live_cycle_scope import live_cycle_scope
    from runtime_store.planning_clock import planning_freeze
    from runtime_store.push_read_replay import replay_push_reads

    start_state = entry.get("start_state") or {}
    # Only enter fail-loud serve mode when the key was recorded. Older cycles
    # omit it and still fetch (or use ambient fallback) as before. A recorded
    # ``None`` means the live cycle read no forecast: any read now fails loud.
    has_outdoor_forecast = "outdoor_forecast" in start_state
    recorded_forecast = start_state.get("outdoor_forecast") if has_outdoor_forecast else None
    if recorded_forecast is not None and not isinstance(recorded_forecast, dict):
        raise TypeError("start_state.outdoor_forecast must be a dict when present")
    moment = _recorded_planning_moment(entry)
    _rebind_consumer_state_path()
    with ExitStack() as stack:
        # Same cycle semantics as main: Live thermal planning also when the live snapshot was
        # rejected and row 0 stayed ``forecast`` (``is_live_thermal_planning``). Without the
        # scope such a cycle planned the heat pump with SE day targets (cycle 2026-11-01 16:44).
        stack.enter_context(live_cycle_scope())
        stack.enter_context(planning_freeze(moment))
        if has_outdoor_forecast:
            stack.enter_context(replay_outdoor_forecast(recorded_forecast))
        # Cycles recorded before push_reads existed read the local inbox as before.
        if "push_reads" in start_state:
            stack.enter_context(replay_push_reads(start_state["push_reads"]))
        stack.enter_context(_recorded_ev_limit_soc(entry, config))
        stack.enter_context(_recorded_thermal_readings(entry))
        prepared_ctx = _prepare_replay_inputs(entry, config)
        begin_cbc_event_collection()
        begin_solve_log()
        t0 = time.perf_counter()
        result = _run_milp_replay(
            prepared_ctx,
            verbose=verbose,
            sunrise_soc_min_index=_recorded_sunrise_soc_min_index(entry),
        )
    result.seconds = time.perf_counter() - t0
    result.stage = _stage_from_events(take_cbc_events(), solver_mode)
    result.solver = take_solve_log()
    result.timestamp = entry.get("timestamp")
    result.config_hash = str(entry.get("config_hash") or "")
    return result


@dataclass
class _PreparedReplay:
    prepared: list[dict[str, Any]]
    contexts: dict[str, dict]
    filter_contexts: dict[str, dict]
    remaining: dict[str, float]
    consumers: list
    battery_params: dict | list[dict]
    soc: float
    soc_by_id: dict[str, float] | None
    current_hour: int
    continue_on: dict[str, bool]
    inverter_params: list[dict] | None
    pv_systems: list[dict] | None
    k_push: float
    hk_max_export_kw: float | None = None
    inbound_export_limit_kw: float | None = None
    import_caps: Any = None
    # Observe mode of the cap (P6d): the executed plan had no cap, the report came from a second plan.
    import_cap_observe: bool = False


def _prepare_replay_inputs(entry: dict[str, Any], config_module: Any) -> _PreparedReplay:
    from optimizer import (
        get_consumer_remaining_kwh,
        get_generic_flex_continue_on,
        prepare_optimization_matrix,
        resolve_filter_contexts,
    )

    matrix = restore_matrix_from_entry(entry)
    start_state = entry.get("start_state") or {}
    consumers = list(config_module.get_flexible_consumers(optimizer_only=True) or [])
    targets_hint = start_state.get("targets")
    if targets_hint is not None and not isinstance(targets_hint, dict):
        raise TypeError("start_state.targets must be a dict when present")
    prepared, contexts, targets = prepare_optimization_matrix(
        matrix,
        targets_hint,
        consumers=consumers,
    )
    filter_contexts = resolve_filter_contexts(prepared, consumers)
    remaining = get_consumer_remaining_kwh(
        consumers=consumers,
        optimization_matrix=prepared,
        consumer_daily_targets_kwh=targets,
        charging_contexts=contexts,
        filter_contexts=filter_contexts,
    )
    soc = start_state.get("soc_percent")
    if soc is None:
        raise ValueError("start_state.soc_percent missing")
    soc_by_id_raw = start_state.get("soc_percent_by_ess") or None
    if soc_by_id_raw is not None and not isinstance(soc_by_id_raw, dict):
        raise TypeError("start_state.soc_percent_by_ess must be a dict when present")
    soc_by_id = (
        {str(k): float(v) for k, v in soc_by_id_raw.items()} if soc_by_id_raw else None
    )
    return _PreparedReplay(
        prepared=prepared,
        contexts=contexts,
        filter_contexts=filter_contexts,
        remaining=remaining,
        consumers=consumers,
        battery_params=_filter_batteries_with_soc(
            _battery_params_with_recorded_reserves(
                _battery_params_with_recorded_ess_limits(
                    _battery_params_from_config(config_module),
                    start_state,
                ),
                start_state,
            ),
            soc_by_id,
            start_state,
        ),
        soc=float(soc),
        soc_by_id=soc_by_id,
        current_hour=int(
            prepared[0].get("hour") or prepared[0]["slot_datetime"].hour
        ),
        continue_on=get_generic_flex_continue_on(contexts, consumers),
        inverter_params=_inverter_params_from_config(config_module),
        pv_systems=_pv_systems_from_config(config_module),
        k_push=_require_push_price_cent(config_module),
        **_recorded_export_limits(start_state),
        import_caps=_recorded_import_caps(start_state),
        import_cap_observe=_recorded_import_cap_observe(start_state),
    )


def _apply_recorded_standby_relief(ctx: _PreparedReplay) -> None:
    """Relieve house load the way the live cycle does after ``begin_cycle``.

    The recorder snapshots the matrix before this step. The pack, its SoC and
    the matrix determine the island schedule, so replay can rebuild it.
    """
    from optimizer.powerstation_live import load_standby_packs
    from optimizer.powerstation_standby import (
        apply_standby_load_relief,
        plan_standby_horizon,
    )
    from optimizer.slot_duration import DEFAULT_DT_H

    packs = load_standby_packs(telemetry=None)
    plans = plan_standby_horizon(
        ctx.prepared,
        packs,
        current_soc_by_id=ctx.soc_by_id,
        dt_h=DEFAULT_DT_H,
    )
    if not plans:
        return
    ctx.prepared = apply_standby_load_relief(ctx.prepared, plans)


def _run_milp_replay(
    ctx: _PreparedReplay,
    *,
    verbose: bool,
    sunrise_soc_min_index: int | None,
) -> ReplayResult:
    from optimizer.milp import (
        _extract_optimizer_controls_from_model,
        _primary_battery_params,
        _solve_milp_to_model,
        shadow_import_cap_report,
    )

    _apply_recorded_standby_relief(ctx)
    solve_args: dict[str, Any] = {
        "matrix": ctx.prepared,
        "current_soc": ctx.soc,
        "battery_params": ctx.battery_params,
        "k_push": ctx.k_push,
        "verbose": verbose,
        "consumers": ctx.consumers,
        "consumer_remaining_kwh": ctx.remaining,
        "spa_remaining_kwh": None,
        "flex_indices": None,
        "charging_contexts": ctx.contexts,
        "filter_contexts": ctx.filter_contexts,
        "terminal_soc_percent": None,
        "sunrise_soc_min_index": sunrise_soc_min_index,
        "consumer_continue_on": ctx.continue_on,
        "thermal_flex_contexts": None,
        "hk_max_export_kw": ctx.hk_max_export_kw,
        "inbound_export_limit_kw": ctx.inbound_export_limit_kw,
        "current_soc_by_id": ctx.soc_by_id,
        "inverter_params": ctx.inverter_params,
        "pv_systems": ctx.pv_systems,
    }
    solved = _solve_milp_to_model(
        **solve_args, import_caps=None if ctx.import_cap_observe else ctx.import_caps
    )
    primary = _primary_battery_params(ctx.battery_params)
    if solved is None:
        return _replay_from_optimizer_fallback(
            ctx,
            primary,
            verbose=verbose,
            sunrise_soc_min_index=sunrise_soc_min_index,
        )

    model, preset_by_slot, remaining, _idx, _c, _f = solved
    controls = _extract_optimizer_controls_from_model(
        model, ctx.prepared, preset_by_slot, ctx.soc, primary
    )
    report = None
    if ctx.import_caps is not None and ctx.import_cap_observe:
        report = shadow_import_cap_report(
            model, ctx.prepared, ctx.import_caps, solve_args, ctx.k_push
        )
    elif ctx.import_caps is not None:
        from optimizer.import_cap_report import report_from_model

        report = report_from_model(model, ctx.prepared, ctx.import_caps, remaining)
    return _milp_replay_result(ctx, model, controls, primary, import_cap_report=report)


def _milp_replay_result(
    ctx: _PreparedReplay,
    model,
    controls,
    primary: dict,
    *,
    import_cap_report: dict[str, Any] | None = None,
) -> ReplayResult:
    """Replay result (plan hash, cost, controls) from the solved MILP model."""
    import pulp
    from optimizer import battery_plan_kw_from_control
    from runtime_store.cycle_recorder import compute_plan_hash

    battery_plan = battery_plan_kw_from_control(
        controls.mode,
        controls.target_power,
        ctx.prepared[0]["expected_p_pv"],
        ctx.prepared[0]["expected_p_act"],
        sum(float(v) for v in controls.consumer_powers.values()),
        primary["max_power_kw"],
    )
    objective_raw = pulp.value(model.prob.objective)
    plan_hash = compute_plan_hash(
        mode=int(controls.mode),
        target_power_kw=round(float(controls.target_power), 3),
        battery_plan_kw=battery_plan,
        consumer_powers_kw={
            k: round(float(v), 3) for k, v in controls.consumer_powers.items()
        },
    )
    return ReplayResult(
        n_slots=len(ctx.prepared),
        seconds=0.0,
        stage="unknown",
        status="Optimal",
        plan_hash=plan_hash,
        cost_euro=None if objective_raw is None else float(objective_raw) / 100.0,
        objective_raw=None if objective_raw is None else float(objective_raw),
        mode=int(controls.mode),
        target_power_kw=float(controls.target_power),
        battery_plan_kw=float(battery_plan) if battery_plan is not None else None,
        consumer_powers_kw={k: float(v) for k, v in controls.consumer_powers.items()},
        import_cap_report=import_cap_report,
    )


def _replay_from_optimizer_fallback(
    ctx: _PreparedReplay,
    primary: dict,
    *,
    verbose: bool,
    sunrise_soc_min_index: int | None,
) -> ReplayResult:
    from optimizer import battery_plan_kw_from_control, milp_optimizer
    from runtime_store.cycle_recorder import compute_plan_hash

    mode, target_power, _ts, consumer_powers, _pf, plan, _obs = milp_optimizer(
        ctx.prepared,
        ctx.current_hour,
        ctx.soc,
        battery_params=ctx.battery_params,
        consumers=ctx.consumers,
        consumer_remaining_kwh=ctx.remaining,
        charging_contexts=ctx.contexts,
        filter_contexts=ctx.filter_contexts,
        sunrise_soc_min_index=sunrise_soc_min_index,
        consumer_continue_on=ctx.continue_on,
        hk_max_export_kw=ctx.hk_max_export_kw,
        inbound_export_limit_kw=ctx.inbound_export_limit_kw,
        verbose=verbose,
        current_soc_by_id=ctx.soc_by_id,
        import_caps=ctx.import_caps,
        import_cap_observe=ctx.import_cap_observe,
    )
    battery_plan = battery_plan_kw_from_control(
        mode,
        target_power,
        ctx.prepared[0]["expected_p_pv"],
        ctx.prepared[0]["expected_p_act"],
        sum(float(v) for v in consumer_powers.values()),
        primary["max_power_kw"],
    )
    plan_hash = compute_plan_hash(
        mode=int(mode),
        target_power_kw=round(float(target_power), 3),
        battery_plan_kw=battery_plan,
        consumer_powers_kw={k: round(float(v), 3) for k, v in consumer_powers.items()},
    )
    return ReplayResult(
        n_slots=len(ctx.prepared),
        seconds=0.0,
        stage="unknown",
        status="no_optimal",
        plan_hash=plan_hash,
        cost_euro=None,
        objective_raw=None,
        mode=int(mode),
        target_power_kw=float(target_power),
        battery_plan_kw=float(battery_plan) if battery_plan is not None else None,
        consumer_powers_kw={k: float(v) for k, v in consumer_powers.items()},
        import_cap_report=(plan or {}).get("import_cap_report"),
    )


def _stage_from_events(events: list[dict[str, Any]], solver_mode: SolverMode) -> str:
    if solver_mode == "strict":
        return "strict_only"
    for event in events:
        if event.get("event") == "strict_fallback":
            return "fallback"
    return "strict"


def solve_hit_time_limit(record: dict[str, Any]) -> bool:
    """True when the plan of one solve record comes from a stage stopped at its time limit."""
    if record.get("stage") in ("strict", "strict_incumbent"):
        return bool(record.get("strict_time_limit_hit"))
    if record.get("stage") == "gap":
        return bool(record.get("gap_time_limit_hit"))
    return False


def recorded_time_limit_hit(entry: dict[str, Any]) -> bool | None:
    """Whether the live cycle's plan came from a solve stopped at a time limit.

    ``None`` for cycles recorded before ``outputs.solver`` existed: unknown, not ``False``.
    """
    solver = (entry.get("outputs") or {}).get("solver")
    if solver is None:
        return None
    return any(solve_hit_time_limit(rec) for rec in solver)
