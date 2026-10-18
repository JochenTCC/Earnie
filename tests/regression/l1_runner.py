"""L1 cycle replay via recorder_replay (strict HiGHS)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime_store.cycle_recorder import read_segment_cycles
from runtime_store.recorder_replay import ReplayResult, replay_recorded_cycle
from tests.regression.fingerprint import l1_input_fingerprint
from tests.regression.loader import RegressionCase, resolve_recorder_root


def select_cycle_entry(case: RegressionCase) -> tuple[dict[str, Any], Path]:
    recorder_root = resolve_recorder_root(case)
    recorder = case.meta["recorder"]
    entries = _load_all_cycles(recorder_root)
    if not entries:
        raise ValueError(f"no cycles in recorder root {recorder_root}")
    seed_anchor = recorder.get("seed_anchor")
    if seed_anchor is not None:
        for entry in entries:
            window = entry.get("planning_window") or {}
            if str(window.get("seed_anchor") or "") == str(seed_anchor):
                return entry, recorder_root
        raise ValueError(
            f"case {case.id}: no cycle with seed_anchor={seed_anchor!r} "
            f"in {recorder_root}"
        )
    index = int(recorder["cycle_index"])
    if index < 0 or index >= len(entries):
        raise ValueError(
            f"case {case.id}: cycle_index {index} out of range "
            f"(0..{len(entries) - 1})"
        )
    return entries[index], recorder_root


def run_l1(case: RegressionCase) -> dict[str, Any]:
    entry, recorder_root = select_cycle_entry(case)
    result = replay_recorded_cycle(
        entry,
        recorder_root=recorder_root,
        solver_mode="strict",
        verbose=False,
    )
    metrics = metrics_from_replay(result)
    metrics["inputs"] = l1_input_fingerprint(entry=entry, recorder_root=recorder_root)
    return metrics


def metrics_from_replay(result: ReplayResult) -> dict[str, Any]:
    consumer_energy = {
        f"consumer_energy_kw_slot0_{cid}": float(val)
        for cid, val in sorted((result.consumer_powers_kw or {}).items())
    }
    return {
        "status_optimal": 1 if str(result.status).lower() == "optimal" else 0,
        "n_slots": int(result.n_slots),
        "cost_euro": result.cost_euro,
        "objective_raw": result.objective_raw,
        "mode": int(result.mode),
        "target_power_kw": float(result.target_power_kw),
        "battery_plan_kw": (
            None if result.battery_plan_kw is None else float(result.battery_plan_kw)
        ),
        "plan_hash": result.plan_hash,
        **consumer_energy,
    }


def _load_all_cycles(recorder_root: Path) -> list[dict[str, Any]]:
    segments = sorted(recorder_root.glob("cycles_*.jsonl.gz"))
    if not segments:
        raise FileNotFoundError(f"no cycles_*.jsonl.gz under {recorder_root}")
    entries: list[dict[str, Any]] = []
    for segment in segments:
        entries.extend(read_segment_cycles(segment))
    return entries
