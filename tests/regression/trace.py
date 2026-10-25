"""Subprocess entry for ``run_regression --compare-at``: run one case in a given tree.

    python tests/regression/trace.py <tree> <case_dir> <out_dir>

Imports Earnie code from ``<tree>`` (any commit that has the regression harness).
Only ``fingerprint.py`` is loaded from the calling checkout, so both sides of a
comparison are hashed identically. Writes ``<out_dir>/trace.json`` and, for L2,
``<out_dir>/slots.csv`` (per-slot inputs and decisions).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

L2_TRACE_COLUMNS = (
    "pv_kw",
    "baseload_kw",
    "consumption_kw",
    "k_act",
    "k_push_act",
    "batt_action_kw",
    "sim_soc",
    "import_kwh",
    "export_kwh",
    "sim_cost",
)
_FIXTURE_ENV = {
    "EARNIE_CONFIG_PATH": "config.json",
    "EARNIE_BACKTESTING_SCENARIOS_PATH": "backtesting_scenarios.json",
    "EARNIE_TARIFFS_PATH": "tariffs.json",
    "EARNIE_HOUSE_PROFILES_PATH": "house_profiles.json",
}


def _load_fingerprint_module() -> Any:
    path = Path(__file__).resolve().with_name("fingerprint.py")
    spec = importlib.util.spec_from_file_location("_regression_fingerprint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_process(tree: Path) -> None:
    """Import from ``tree`` only; bind config to its offline fixtures (no earnie_env)."""
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(script_dir)]
    sys.path.insert(0, str(tree))
    os.chdir(tree)
    os.environ["EARNIE_OFFLINE"] = "1"
    os.environ["EARNIE_CBC_STRICT"] = "1"
    os.environ.setdefault("EARNIE_MILP_SOLVER", "highs")
    fixtures = tree / "tests" / "fixtures" / "backtesting"
    for key, name in _FIXTURE_ENV.items():
        os.environ[key] = str(fixtures / name)


def _patch_pv_column() -> None:
    """Trees before f43e8bec lack ``pv_kw`` in the result frame; add it from the chart rows."""
    import simulation.engine as engine

    original = engine._finalize_simulation_result

    def wrapped(all_chart_rows, *args, **kwargs):
        df = original(all_chart_rows, *args, **kwargs)
        if "pv_kw" not in df.columns:
            df["pv_kw"] = [float(row["PV-Prognose (kW)"]) for row in all_chart_rows]
        return df

    engine._finalize_simulation_result = wrapped


def _trace_l2(case: Any, tree: Path, out_dir: Path, fp: Any) -> dict[str, Any]:
    import tests.regression.l2_runner as l2

    _patch_pv_column()
    captured: dict[str, Any] = {}
    original_metrics = l2.metrics_from_l2_frame

    def capture(df, plausibility):
        captured["df"] = df
        return original_metrics(df, plausibility)

    l2.metrics_from_l2_frame = capture
    if hasattr(l2, "assert_pv_day_shape"):
        # Record the PV-shape guard instead of aborting: the trace is wanted most then.
        guard = l2.assert_pv_day_shape

        def record_guard(df, *, case_id):
            try:
                guard(df, case_id=case_id)
            except ValueError as exc:  # ImplausiblePvInputError
                captured["pv_shape_error"] = str(exc)

        l2.assert_pv_day_shape = record_guard
    metrics = l2.run_l2(case)
    metrics.pop("inputs", None)
    plan_hash = metrics.pop("plan_hash", None)
    df = captured["df"]
    columns = [c for c in L2_TRACE_COLUMNS if c in df.columns]
    df[columns].to_csv(out_dir / "slots.csv", index_label="ts")
    inputs = fp.l2_input_fingerprint(
        fixtures_root=tree / "tests" / "fixtures" / "backtesting",
        case_inputs=dict(case.meta.get("inputs") or {}),
        result_df=df,
    )
    return {
        "metrics": metrics,
        "plan_hash": plan_hash,
        "inputs": inputs,
        "pv_shape_error": captured.get("pv_shape_error"),
        "slots": True,
    }


def _trace_l1(case: Any, fp: Any) -> dict[str, Any]:
    from tests.regression.l1_runner import run_l1, select_cycle_entry

    entry, recorder_root = select_cycle_entry(case)
    metrics = run_l1(case)
    tree_inputs = metrics.pop("inputs", None) or {}
    plan_hash = metrics.pop("plan_hash", None)
    inputs = fp.l1_input_fingerprint(entry=entry, recorder_root=recorder_root)
    # Climate digests come from the tree's runner (the files it actually read).
    inputs["files"].update(
        {k: v for k, v in (tree_inputs.get("files") or {}).items() if k.startswith("open_meteo/")}
    )
    return {
        "metrics": metrics,
        "plan_hash": plan_hash,
        "inputs": inputs,
        "pv_shape_error": None,
        "slots": False,
    }


def main(argv: list[str]) -> int:
    tree, case_dir, out_dir = (Path(a).resolve() for a in argv)
    fp = _load_fingerprint_module()
    _prepare_process(tree)
    if not (tree / "tests" / "regression" / "loader.py").is_file():
        raise SystemExit(f"{tree} has no regression harness (tests/regression/loader.py)")
    from tests.regression.loader import load_case

    out_dir.mkdir(parents=True, exist_ok=True)
    case = load_case(case_dir, require_expected=False)
    if case.level == "L2":
        result = _trace_l2(case, tree, out_dir, fp)
    elif case.level == "L1":
        result = _trace_l1(case, fp)
    else:
        raise SystemExit(f"--compare-at supports L1 / L2 cases, not {case.level!r}")
    result["level"] = case.level
    (out_dir / "trace.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=float) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
