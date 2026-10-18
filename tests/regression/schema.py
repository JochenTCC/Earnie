"""Validate regression case.yaml and expected.json (fail loud)."""
from __future__ import annotations

from typing import Any

LEVELS = frozenset({"L1", "L2", "L1-invariants"})
SOURCES = frozenset({"synthetic", "own", "customer"})
DEFAULT_METRIC_TOLERANCE_PCT = 0.05

_CASE_REQUIRED = ("id", "title", "level", "source", "anonymized")
_EXPECTED_REQUIRED = ("engine", "tolerances", "invariants", "metrics")


def validate_case_meta(meta: dict[str, Any], *, case_dir_name: str) -> None:
    if not isinstance(meta, dict):
        raise TypeError(f"case.yaml must be a mapping ({case_dir_name})")
    missing = [k for k in _CASE_REQUIRED if k not in meta]
    if missing:
        raise ValueError(
            f"case.yaml in {case_dir_name} missing required keys: {missing}"
        )
    case_id = meta["id"]
    if not isinstance(case_id, str) or not case_id:
        raise ValueError(f"case.yaml id must be a non-empty string ({case_dir_name})")
    if case_id != case_dir_name:
        raise ValueError(
            f"case.yaml id {case_id!r} must match folder name {case_dir_name!r}"
        )
    level = meta["level"]
    if level not in LEVELS:
        raise ValueError(
            f"case.yaml level {level!r} invalid; expected one of {sorted(LEVELS)}"
        )
    source = meta["source"]
    if source not in SOURCES:
        raise ValueError(
            f"case.yaml source {source!r} invalid; expected one of {sorted(SOURCES)}"
        )
    if not isinstance(meta["anonymized"], bool):
        raise TypeError(f"case.yaml anonymized must be bool ({case_dir_name})")
    if level == "L1":
        _require_recorder_select(meta, case_dir_name)
    elif level == "L2":
        _require_l2_window(meta, case_dir_name)
    elif level == "L1-invariants":
        if not meta.get("prod_dump_id"):
            raise ValueError(
                f"L1-invariants case {case_dir_name} requires prod_dump_id"
            )


def _require_recorder_select(meta: dict[str, Any], case_dir_name: str) -> None:
    recorder = meta.get("recorder")
    if not isinstance(recorder, dict):
        raise ValueError(
            f"L1 case {case_dir_name} requires recorder: {{root, seed_anchor|cycle_index}}"
        )
    if not recorder.get("root"):
        raise ValueError(f"L1 case {case_dir_name} recorder.root missing")
    if recorder.get("seed_anchor") is None and recorder.get("cycle_index") is None:
        raise ValueError(
            f"L1 case {case_dir_name} needs recorder.seed_anchor or cycle_index"
        )


def _require_l2_window(meta: dict[str, Any], case_dir_name: str) -> None:
    window = meta.get("window")
    if not isinstance(window, dict) or not window.get("start") or not window.get("end"):
        raise ValueError(
            f"L2 case {case_dir_name} requires window: {{start, end}} (ISO dates)"
        )
    inputs = meta.get("inputs")
    if not isinstance(inputs, dict) or inputs.get("kind") != "backtesting_fixtures":
        raise ValueError(
            f"L2 case {case_dir_name} requires inputs.kind=backtesting_fixtures"
        )


def validate_expected(expected: dict[str, Any], *, case_id: str) -> None:
    if not isinstance(expected, dict):
        raise TypeError(f"expected.json must be a mapping ({case_id})")
    missing = [k for k in _EXPECTED_REQUIRED if k not in expected]
    if missing:
        raise ValueError(f"expected.json in {case_id} missing keys: {missing}")
    engine = expected["engine"]
    if not isinstance(engine, dict):
        raise TypeError(f"expected.engine must be a mapping ({case_id})")
    for key in ("earnie_version", "solver", "solver_mode"):
        if key not in engine:
            raise ValueError(f"expected.engine.{key} missing ({case_id})")
    tolerances = expected["tolerances"]
    if not isinstance(tolerances, dict) or "default_pct" not in tolerances:
        raise ValueError(f"expected.tolerances.default_pct missing ({case_id})")
    if not isinstance(expected["invariants"], list):
        raise TypeError(f"expected.invariants must be a list ({case_id})")
    if not isinstance(expected["metrics"], dict):
        raise TypeError(f"expected.metrics must be a mapping ({case_id})")
    if "baseline" in expected:
        _validate_baseline(expected["baseline"], case_id)
    if "inputs" in expected:
        _validate_inputs(expected["inputs"], case_id)


def _validate_baseline(baseline: Any, case_id: str) -> None:
    from tests.regression.baseline import BASELINE_SOURCES

    if not isinstance(baseline, dict):
        raise TypeError(f"expected.baseline must be a mapping ({case_id})")
    sha = baseline.get("git_sha")
    if not isinstance(sha, str) or len(sha) != 40:
        raise ValueError(f"expected.baseline.git_sha must be a full 40-char SHA ({case_id})")
    if not isinstance(baseline.get("recorded_at"), str):
        raise ValueError(f"expected.baseline.recorded_at missing ({case_id})")
    if baseline.get("source") not in BASELINE_SOURCES:
        raise ValueError(
            f"expected.baseline.source must be one of {sorted(BASELINE_SOURCES)} ({case_id})"
        )


def _validate_inputs(inputs: Any, case_id: str) -> None:
    if not isinstance(inputs, dict):
        raise TypeError(f"expected.inputs must be a mapping ({case_id})")
    for layer in ("files", "series", "sums"):
        if not isinstance(inputs.get(layer), dict):
            raise ValueError(f"expected.inputs.{layer} must be a mapping ({case_id})")


def default_tolerances() -> dict[str, Any]:
    return {"default_pct": DEFAULT_METRIC_TOLERANCE_PCT, "per_metric_pct": {}}
