"""Golden compare: invariants / metrics gate; plan diff and inputs are informational."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.regression.fingerprint import diff_inputs
from tests.regression.schema import DEFAULT_METRIC_TOLERANCE_PCT

INFO_TIERS = frozenset({"plan_diff", "inputs"})


@dataclass
class TierResult:
    name: str
    passed: bool
    messages: list[str] = field(default_factory=list)


@dataclass
class CompareResult:
    case_id: str
    tiers: list[TierResult]
    actual_metrics: dict[str, Any] = field(default_factory=dict)
    plan_diff: dict[str, Any] = field(default_factory=dict)
    baseline: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.tiers if t.name not in INFO_TIERS)


def compare_case(
    *,
    case_id: str,
    expected: dict[str, Any],
    actual_metrics: dict[str, float | int | None],
    invariant_failures: list[str],
    actual_plan_hash: str | None = None,
    actual_inputs: dict[str, Any] | None = None,
    actual_engine: dict[str, Any] | None = None,
) -> CompareResult:
    tier1 = TierResult(
        name="invariants",
        passed=not invariant_failures,
        messages=list(invariant_failures),
    )
    tier2 = _compare_metrics(expected, actual_metrics)
    expected_hash = None
    plan = expected.get("plan") or {}
    if isinstance(plan, dict):
        expected_hash = plan.get("plan_hash")
    diff_slots = plan.get("diff_slots") if isinstance(plan, dict) else None
    hash_changed = (
        expected_hash is not None
        and actual_plan_hash is not None
        and str(expected_hash) != str(actual_plan_hash)
    )
    tier3 = TierResult(
        name="plan_diff",
        passed=True,
        messages=(
            [
                f"plan_hash expected={expected_hash} actual={actual_plan_hash}"
                + (" (changed)" if hash_changed else "")
            ]
            if actual_plan_hash is not None or expected_hash is not None
            else ["n/a (no plan hash for this case level)"]
        ),
    )
    tier4 = _compare_inputs(
        expected,
        actual_inputs,
        actual_engine=actual_engine,
        metrics_failed=not tier2.passed,
    )
    return CompareResult(
        case_id=case_id,
        tiers=[tier1, tier2, tier3, tier4],
        actual_metrics=dict(actual_metrics),
        plan_diff={
            "expected_plan_hash": expected_hash,
            "actual_plan_hash": actual_plan_hash,
            "hash_changed": hash_changed,
            "diff_slots": diff_slots,
        },
    )


def _compare_metrics(
    expected: dict[str, Any],
    actual: dict[str, float | int | None],
) -> TierResult:
    tolerances = expected.get("tolerances") or {}
    default_pct = float(
        tolerances.get("default_pct", DEFAULT_METRIC_TOLERANCE_PCT)
    )
    per_metric = tolerances.get("per_metric_pct") or {}
    want = expected.get("metrics") or {}
    messages: list[str] = []
    for key, exp_raw in want.items():
        if exp_raw is None:
            continue
        if key not in actual:
            messages.append(f"metric {key!r} missing from actual")
            continue
        act_raw = actual[key]
        if act_raw is None:
            messages.append(f"metric {key!r} actual is None")
            continue
        exp = float(exp_raw)
        act = float(act_raw)
        tol_pct = float(per_metric.get(key, default_pct))
        if exp == 0.0:
            ok = abs(act) <= 1e-9
            if not ok:
                messages.append(
                    f"{key}: expected 0, actual {act} (zero-metric absolute check)"
                )
            continue
        delta_pct = abs(act - exp) / abs(exp) * 100.0
        if delta_pct > tol_pct:
            messages.append(
                f"{key}: expected {exp}, actual {act}, "
                f"Δ={delta_pct:.4f}% > tol {tol_pct}%"
            )
    return TierResult(name="metrics", passed=not messages, messages=messages)


def _compare_inputs(
    expected: dict[str, Any],
    actual_inputs: dict[str, Any] | None,
    *,
    actual_engine: dict[str, Any] | None,
    metrics_failed: bool,
) -> TierResult:
    """Informational: which inputs moved, plus a verdict when metrics failed."""
    messages: list[str] = []
    exp_version = (expected.get("engine") or {}).get("earnie_version")
    act_version = (actual_engine or {}).get("earnie_version")
    if exp_version and act_version and exp_version != act_version:
        messages.append(f"engine: earnie_version {exp_version} → {act_version}")

    expected_inputs = expected.get("inputs")
    if not expected_inputs:
        messages.append("no input fingerprint in expected.json (golden predates it)")
        actual_sums = (actual_inputs or {}).get("sums") or {}
        if actual_sums:
            messages.append(
                "actual: " + ", ".join(f"{k}={v}" for k, v in sorted(actual_sums.items()))
            )
        if metrics_failed:
            messages.append(
                "verdict: cannot separate input drift from a code change — "
                "re-record with --update-golden once the cause is understood"
            )
        return TierResult(name="inputs", passed=True, messages=messages)
    if not actual_inputs:
        messages.append("no input fingerprint for the actual run")
        return TierResult(name="inputs", passed=True, messages=messages)

    diff = diff_inputs(expected_inputs, actual_inputs)
    if diff["files"]:
        messages.append("files changed: " + ", ".join(diff["files"]))
    if diff["series"]:
        messages.append("effective input series changed: " + ", ".join(diff["series"]))
    for key, (old, new) in diff["sums"].items():
        messages.append(f"{key}: {old} → {new}")
    if not (diff["files"] or diff["series"]):
        messages.append("inputs identical")

    if metrics_failed:
        if diff["series"]:
            verdict = (
                "effective inputs changed — check test data / input preparation "
                "before suspecting the optimizer"
            )
        elif diff["files"]:
            verdict = (
                "input files changed but effective inputs identical — "
                "behaviour change in code; bisect from baseline"
            )
        else:
            verdict = "inputs identical — behaviour change in code; bisect from baseline"
        messages.append(f"verdict: {verdict}")
    return TierResult(name="inputs", passed=True, messages=messages)


def build_expected_payload(
    *,
    engine: dict[str, Any],
    metrics: dict[str, Any],
    invariants: list[dict[str, Any]] | None = None,
    plan_hash: str | None = None,
    tolerances: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from tests.regression.schema import default_tolerances

    payload: dict[str, Any] = {
        "engine": engine,
        "tolerances": tolerances or default_tolerances(),
        "invariants": list(invariants or []),
        "metrics": metrics,
        "plan": {"plan_hash": plan_hash, "diff_slots": None},
    }
    if baseline is not None:
        payload["baseline"] = baseline
    if inputs is not None:
        payload["inputs"] = inputs
    return payload
