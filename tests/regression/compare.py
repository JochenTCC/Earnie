"""Three-tier golden compare (invariants / metrics / plan diff)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.regression.schema import DEFAULT_METRIC_TOLERANCE_PCT


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

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.tiers if t.name != "plan_diff")


def compare_case(
    *,
    case_id: str,
    expected: dict[str, Any],
    actual_metrics: dict[str, float | int | None],
    invariant_failures: list[str],
    actual_plan_hash: str | None = None,
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
            else []
        ),
    )
    return CompareResult(
        case_id=case_id,
        tiers=[tier1, tier2, tier3],
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


def build_expected_payload(
    *,
    engine: dict[str, Any],
    metrics: dict[str, Any],
    invariants: list[dict[str, Any]] | None = None,
    plan_hash: str | None = None,
    tolerances: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from tests.regression.schema import default_tolerances

    payload: dict[str, Any] = {
        "engine": engine,
        "tolerances": tolerances or default_tolerances(),
        "invariants": list(invariants or []),
        "metrics": metrics,
        "plan": {"plan_hash": plan_hash, "diff_slots": None},
    }
    return payload
