"""Offline MILP replay from cycle-recorder entries (Regression R0 / P1/L3).

Replays **replay-vs-replay** from frozen pre-prepare inputs. Live post-capture
mutations (standby relief, EHAL telemetry) are intentionally omitted.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

SolverMode = Literal["production", "strict"]

_ARCHIVE_TO_ENV: dict[str, str] = {
    "inputs/config.json": "config/config.json",
    "inputs/components.json": "config/components.json",
    "inputs/tariffs.json": "config/tariffs.json",
    "inputs/user_tariffs.json": "config/user_tariffs.json",
    "inputs/grid_fees.json": "config/grid_fees.json",
    "inputs/user_grid_fees.json": "config/user_grid_fees.json",
    "inputs/house_profiles.json": "config/house_profiles.json",
    "inputs/backtesting_scenarios.json": "config/backtesting_scenarios.json",
    "inputs/deviation_rules.json": "config/deviation_rules.json",
    "inputs/local_settings.json": "runtime/local_settings.json",
    "inputs/price_model_coefficients.json": "runtime/price_model_coefficients.json",
    "inputs/cons_data.csv": "runtime/cons_data.csv",
}

_ENV_CLEAR_SUFFIXES = (
    "CONFIG_PATH",
    "COMPONENTS_PATH",
    "DEVIATION_RULES_PATH",
    "GRID_FEES_PATH",
    "HOUSE_PROFILES_PATH",
    "LOCAL_SETTINGS_PATH",
    "RUNTIME_PATH",
    "TARIFFS_PATH",
    "BACKTESTING_SCENARIOS_PATH",
)


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


def load_config_snapshot(recorder_root: Path | str, config_hash: str) -> dict[str, Any]:
    """Load ``configs/{config_hash}.json`` or raise."""
    root = Path(recorder_root)
    path = root / "configs" / f"{config_hash}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"recorder config snapshot missing: {path} "
            f"(config_hash={config_hash!r})"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or "files" not in payload:
        raise ValueError(f"invalid config snapshot shape: {path}")
    return payload


def _drop_removed_empty_overlay(content: str) -> str:
    """Recordings made before ``flexible_consumers`` was removed carry ``[]``; a filled block is an error."""
    doc = json.loads(content)
    if not isinstance(doc, dict) or "flexible_consumers" not in doc:
        return content
    if doc["flexible_consumers"]:
        raise ValueError(
            "recorded config.json uses the removed 'flexible_consumers' overlay; "
            "replay needs a recording made after consumers moved to the house profile."
        )
    del doc["flexible_consumers"]
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def materialize_config_snapshot(
    snapshot: dict[str, Any],
    dest_env: Path | str,
) -> Path:
    """Write snapshot ``files`` into an Earnie env tree (config/ + runtime/)."""
    env_root = Path(dest_env)
    files = snapshot.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("config snapshot has no files")
    written = 0
    for archive_name, content in files.items():
        rel = _ARCHIVE_TO_ENV.get(str(archive_name).replace("\\", "/"))
        if rel is None:
            raise ValueError(
                f"unsupported snapshot archive name {archive_name!r}; "
                f"known: {sorted(_ARCHIVE_TO_ENV)}"
            )
        if not isinstance(content, str):
            raise TypeError(
                f"snapshot file {archive_name!r} must be text, got {type(content)!r}"
            )
        if rel == "config/config.json":
            content = _drop_removed_empty_overlay(content)
        target = env_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    if written == 0:
        raise ValueError("config snapshot wrote zero files")
    (env_root / "runtime").mkdir(parents=True, exist_ok=True)
    _migrate_snapshot_config(env_root / "config")
    return env_root


def _migrate_snapshot_config(config_dir: Path) -> None:
    """Archived configs may predate the current data model / tariff format: migrate in memory.

    Same registry steps as the wizard from the recorded data model on, without answers; a
    snapshot that needs an answer or hits a blocker stops the replay with the reason (never
    guessed). Steps of the recorded model itself are skipped: the config ran when recorded.
    """
    from runtime_store.migration.runner import migrate_config_dir_unattended

    written = migrate_config_dir_unattended(
        config_dir, label="recorder config snapshot", model_bump_only=True
    )
    if written:
        logger.debug("replay: migrated snapshot config files %s", ", ".join(written))


def restore_matrix_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Columnar matrix → row dicts with ``datetime`` slot times."""
    from runtime_store.cycle_recorder import columnar_to_matrix

    columnar = entry.get("optimization_matrix")
    if not isinstance(columnar, dict):
        raise ValueError("entry missing optimization_matrix columnar payload")
    n_rows = int(columnar.get("n_rows") or 0)
    if n_rows <= 0:
        raise ValueError("entry optimization_matrix has n_rows <= 0")
    matrix = columnar_to_matrix(columnar)
    if len(matrix) != n_rows:
        raise ValueError(
            f"matrix restore length mismatch: got {len(matrix)}, expected {n_rows}"
        )
    return _coerce_matrix_datetimes(matrix)


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
    from optimizer.cbc_solver import apply_cbc_solver_env, clear_cbc_solver_env

    config.reinit_config()
    clear_cbc_solver_env()
    apply_cbc_solver_env(strict=(solver_mode == "strict"))
    os.environ["EARNIE_MILP_SOLVER"] = "highs"

    with _recorded_ev_limit_soc(entry, config):
        prepared_ctx = _prepare_replay_inputs(entry, config)
        begin_cbc_event_collection()
        t0 = time.perf_counter()
        result = _run_milp_replay(prepared_ctx, verbose=verbose)
    result.seconds = time.perf_counter() - t0
    result.stage = _stage_from_events(take_cbc_events(), solver_mode)
    result.timestamp = entry.get("timestamp")
    result.config_hash = str(entry.get("config_hash") or "")
    return result


@contextmanager
def _recorded_ev_limit_soc(entry: dict[str, Any], config_module: Any):
    """Serve the recorded ``get_evcs_limit_soc`` for the EV markers during replay.

    Fails loud when the marker is actually read but the entry has no recorded
    value (cycles recorded before ``ev_limit_soc_percent`` existed). Cycles that
    never read it replay as before.
    """
    from integrations import ehal_live
    from settings.ehal_marker_resolve import marker_get_evcs_limit_soc

    recorded = (entry.get("start_state") or {}).get("ev_limit_soc_percent") or {}
    cid_by_marker: dict[str, str] = {}
    for consumer in config_module.get_flexible_consumers(optimizer_only=True) or []:
        marker = marker_get_evcs_limit_soc(consumer)
        if marker:
            cid_by_marker[marker] = str(consumer["id"])

    original = ehal_live.read_generic_value

    def _read(address: str):
        cid = cid_by_marker.get(address)
        if cid is None:
            return original(address)
        if cid not in recorded:
            raise ValueError(
                f"entry has no recorded start_state.ev_limit_soc_percent for "
                f"consumer {cid!r} (marker {address!r}); cycle was recorded by an "
                f"older version and cannot be replayed offline"
            )
        return float(recorded[cid])

    ehal_live.read_generic_value = _read
    try:
        yield
    finally:
        ehal_live.read_generic_value = original


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
        battery_params=_battery_params_from_config(config_module),
        soc=float(soc),
        soc_by_id=soc_by_id,
        current_hour=int(
            prepared[0].get("hour") or prepared[0]["slot_datetime"].hour
        ),
        continue_on=get_generic_flex_continue_on(contexts, consumers),
        inverter_params=_inverter_params_from_config(config_module),
        pv_systems=_pv_systems_from_config(config_module),
        k_push=_require_push_price_cent(config_module),
    )


def _require_push_price_cent(config_module: Any) -> float:
    raw = config_module.get_push_price_cent()
    if raw is None:
        raise ValueError(
            "get_push_price_cent() returned None; snapshot export tariff / "
            "push price must be configured for offline replay"
        )
    return float(raw)


def _run_milp_replay(ctx: _PreparedReplay, *, verbose: bool) -> ReplayResult:
    from optimizer.milp import (
        _extract_optimizer_controls_from_model,
        _primary_battery_params,
        _solve_milp_to_model,
    )

    solved = _solve_milp_to_model(
        ctx.prepared,
        ctx.soc,
        ctx.battery_params,
        ctx.k_push,
        verbose,
        ctx.consumers,
        ctx.remaining,
        None,
        None,
        ctx.contexts,
        ctx.filter_contexts,
        None,
        None,
        ctx.continue_on,
        None,
        current_soc_by_id=ctx.soc_by_id,
        inverter_params=ctx.inverter_params,
        pv_systems=ctx.pv_systems,
    )
    primary = _primary_battery_params(ctx.battery_params)
    if solved is None:
        return _replay_from_optimizer_fallback(ctx, primary, verbose=verbose)

    model, preset_by_slot, _rem, _idx, _c, _f = solved
    controls = _extract_optimizer_controls_from_model(
        model, ctx.prepared, preset_by_slot, ctx.soc, primary
    )
    return _milp_replay_result(ctx, model, controls, primary)


def _milp_replay_result(
    ctx: _PreparedReplay, model, controls, primary: dict
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
    )


def _replay_from_optimizer_fallback(
    ctx: _PreparedReplay,
    primary: dict,
    *,
    verbose: bool,
) -> ReplayResult:
    from optimizer import battery_plan_kw_from_control, milp_optimizer
    from runtime_store.cycle_recorder import compute_plan_hash

    mode, target_power, _ts, consumer_powers, _pf, _plan, _obs = milp_optimizer(
        ctx.prepared,
        ctx.current_hour,
        ctx.soc,
        battery_params=ctx.battery_params,
        consumers=ctx.consumers,
        consumer_remaining_kwh=ctx.remaining,
        charging_contexts=ctx.contexts,
        filter_contexts=ctx.filter_contexts,
        consumer_continue_on=ctx.continue_on,
        verbose=verbose,
        current_soc_by_id=ctx.soc_by_id,
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
    )


def _battery_params_from_config(config_module: Any) -> dict | list[dict]:
    get_list = getattr(config_module, "get_battery_params_list", None)
    if callable(get_list):
        batteries = get_list()
        if batteries:
            return batteries
    return config_module.get_battery_params()


def _inverter_params_from_config(config_module: Any) -> list[dict] | None:
    get_list = getattr(config_module, "get_planning_inverters", None)
    if callable(get_list):
        return list(get_list() or [])
    return None


def _pv_systems_from_config(config_module: Any) -> list[dict] | None:
    get_list = getattr(config_module, "get_planning_pv_systems", None)
    if callable(get_list):
        return list(get_list() or [])
    return None


def _stage_from_events(events: list[dict[str, Any]], solver_mode: SolverMode) -> str:
    if solver_mode == "strict":
        return "strict_only"
    for event in events:
        if event.get("event") == "strict_fallback":
            return "fallback"
    return "strict"


def _coerce_matrix_datetimes(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in matrix:
        raw = row.get("slot_datetime")
        if isinstance(raw, datetime):
            slot = raw.replace(tzinfo=None) if raw.tzinfo else raw
        elif isinstance(raw, str):
            slot = datetime.fromisoformat(raw)
            if slot.tzinfo is not None:
                slot = slot.replace(tzinfo=None)
        else:
            raise TypeError(
                f"slot_datetime must be str or datetime, got {type(raw)!r}"
            )
        row["slot_datetime"] = slot
        row["hour"] = int(slot.hour)
        row["date"] = slot.date()
    return matrix


def _write_start_state_files(env_root: Path, start_state: dict[str, Any]) -> None:
    runtime = env_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    mapping = (
        ("flexible_consumers_state", "flexible_consumers_state.json"),
        ("pv_counter_state", "pv_counter_state.json"),
        ("run_state", "optimizer_run_state.json"),
    )
    for key, filename in mapping:
        payload = start_state.get(key)
        if payload is None:
            continue
        path = runtime / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


def _activate_env(env_root: Path) -> dict[str, str | None]:
    previous = {"EARNIE_ENV_PATH": os.environ.get("EARNIE_ENV_PATH")}
    for suffix in _ENV_CLEAR_SUFFIXES:
        key = f"EARNIE_{suffix}"
        previous[key] = os.environ.get(key)
        os.environ.pop(key, None)
    os.environ["EARNIE_ENV_PATH"] = str(env_root)
    os.environ["EARNIE_OFFLINE"] = "1"
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _segment_paths_for_root(root: Path) -> list[Path]:
    from runtime_store import cycle_recorder

    previous = os.environ.get("EARNIE_RUNTIME_PATH")
    try:
        # Segments live under recorder_root directly when passed as study dir,
        # or under runtime/recorder when root is an env runtime/recorder path.
        direct = sorted(root.glob("cycles_*.jsonl.gz"))
        if direct:
            return direct
        os.environ["EARNIE_RUNTIME_PATH"] = str(root.parent)
        return cycle_recorder.list_segment_paths()
    finally:
        if previous is None:
            os.environ.pop("EARNIE_RUNTIME_PATH", None)
        else:
            os.environ["EARNIE_RUNTIME_PATH"] = previous


def _entry_slot_count(entry: dict[str, Any]) -> int:
    columnar = entry.get("optimization_matrix") or {}
    try:
        return int(columnar.get("n_rows") or 0)
    except (TypeError, ValueError):
        return 0


def _entry_is_flagged(entry: dict[str, Any]) -> bool:
    flags = ((entry.get("outputs") or {}).get("flags")) or {}
    return any(
        bool(flags.get(name))
        for name in ("override", "outage", "manual_intervention")
    )


def _best_effort_rmtree(path: Path) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError as exc:
        logger.debug("replay temp cleanup failed: %s", exc)
