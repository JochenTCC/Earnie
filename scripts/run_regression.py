"""Release regression suite runner (golden-master L1 / L2 / prod-dump invariants).

  python -m scripts.run_regression [--cases-dir PATH]... [--case ID] [--workers N]
  python -m scripts.run_regression --update-golden --case REG-O-winter-jan
  python -m scripts.run_regression --intake DUMP.zip --id REG-142-slug --private \\
      --seed-anchor "..." | --cycle-index N

Deselected from the default pytest run (marker ``regression``). Run before
release / publish — see docs/workflow/regression-suite.md and release-checklist.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

os.environ.setdefault("EARNIE_OFFLINE", "1")
os.environ["EARNIE_CBC_STRICT"] = "1"
os.environ.setdefault("EARNIE_MILP_SOLVER", "highs")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Earnie release regression suite (golden-master cases).",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        action="append",
        default=None,
        help=(
            "Case root (repeatable). Default: public tests/regression/cases/ "
            "plus private root when present."
        ),
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        help="Case id to run (repeatable). Default: all discovered cases.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers (default: min(CPU, case count)).",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Rewrite expected.json for selected cases from actual metrics.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "backtesting_logs" / "regression" / "regression_report.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="List cases only; do not execute.",
    )
    parser.add_argument(
        "--intake",
        type=Path,
        default=None,
        help="Debug-dump ZIP → private L1 case (requires --private and selector).",
    )
    parser.add_argument(
        "--id",
        dest="intake_id",
        default=None,
        help="Case id for --intake (REG-<issue>-<slug>).",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Target private cases root (required for --intake).",
    )
    parser.add_argument(
        "--seed-anchor",
        default=None,
        help="L1 cycle seed_anchor for --intake (mutually exclusive with --cycle-index).",
    )
    parser.add_argument(
        "--cycle-index",
        type=int,
        default=None,
        help="L1 cycle index for --intake (mutually exclusive with --seed-anchor).",
    )
    parser.add_argument(
        "--issue",
        default=None,
        help="Optional public issue ref for --intake (e.g. JochenTCC/Earnie#142).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional case title for --intake (defaults to dump meta.title).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing case dir during --intake.",
    )
    return parser.parse_args(argv)


def _case_roots(args: argparse.Namespace) -> tuple[list[Path], list[str], Path | None]:
    """Return (roots, skipped labels, private_cases_dir_or_None)."""
    from tests.regression.loader import (
        DEFAULT_CASES_DIR,
        SKIP_PRIVATE_ROOT_MISSING,
        resolve_private_cases_dir,
    )

    if args.cases_dir:
        return [Path(p) for p in args.cases_dir], [], None

    roots: list[Path] = [DEFAULT_CASES_DIR]
    skipped: list[str] = []
    private = resolve_private_cases_dir()
    if private is not None:
        roots.append(private)
    else:
        skipped.append(SKIP_PRIVATE_ROOT_MISSING)
    return roots, skipped, private


def _worker_count(requested: int | None, n_cases: int) -> int:
    cpu = os.cpu_count() or 1
    useful = max(1, min(cpu, n_cases))
    if requested is None:
        return useful
    if requested < 1:
        raise SystemExit("--workers must be >= 1")
    return min(requested, useful)


def _run_one_case_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Process-pool entry: execute one case and return serializable result."""
    os.environ.setdefault("EARNIE_OFFLINE", "1")
    os.environ["EARNIE_CBC_STRICT"] = "1"
    os.environ.setdefault("EARNIE_MILP_SOLVER", "highs")

    from tests.regression.compare import build_expected_payload, compare_case
    from tests.regression.engine_info import engine_fingerprint
    from tests.regression.l1_runner import run_l1
    from tests.regression.l2_runner import run_l2
    from tests.regression.loader import load_case
    from tests.regression.prod_dump_invariants import run_prod_dump_invariants

    case_dir = Path(payload["case_dir"])
    update_golden = bool(payload["update_golden"])
    case = load_case(case_dir, require_expected=not update_golden)

    invariant_failures: list[str] = []
    actual: dict[str, Any] = {}
    plan_hash: str | None = None

    if case.level == "L1":
        actual = run_l1(case)
        plan_hash = actual.pop("plan_hash", None)
        if actual.get("status_optimal") != 1:
            invariant_failures.append(
                f"solver status not Optimal (got metrics status_optimal="
                f"{actual.get('status_optimal')})"
            )
    elif case.level == "L2":
        actual = run_l2(case)
        plan_hash = actual.pop("plan_hash", None)
        if float(actual.get("plausibility_failures") or 0) > 0:
            invariant_failures.append("plausibility failures > 0")
    elif case.level == "L1-invariants":
        invariant_failures = run_prod_dump_invariants(str(case.meta["prod_dump_id"]))
        actual = {"invariant_count": float(len(case.meta.get("expected_invariants") or []))}
    else:
        raise ValueError(f"unsupported level {case.level!r}")

    metric_keys = {
        k: v
        for k, v in actual.items()
        if isinstance(v, (int, float)) or v is None
    }

    if update_golden:
        expected = build_expected_payload(
            engine=engine_fingerprint(solver_mode="strict"),
            metrics={k: v for k, v in metric_keys.items() if v is not None},
            invariants=list((case.expected or {}).get("invariants") or []),
            plan_hash=plan_hash,
            tolerances=(case.expected or {}).get("tolerances"),
        )
        if case.level == "L1-invariants":
            expected["metrics"] = {}
            expected["invariants"] = [
                {"id": "prod_dump", "prod_dump_id": case.meta["prod_dump_id"]}
            ]
        out_path = case_dir / "expected.json"
        out_path.write_text(
            json.dumps(expected, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {
            "case_id": case.id,
            "passed": True,
            "updated": True,
            "tiers": [],
            "actual_metrics": metric_keys,
            "plan_diff": {"actual_plan_hash": plan_hash},
            "messages": [f"wrote {out_path}"],
        }

    assert case.expected is not None
    compare = compare_case(
        case_id=case.id,
        expected=case.expected,
        actual_metrics=metric_keys,
        invariant_failures=invariant_failures,
        actual_plan_hash=plan_hash,
    )
    return {
        "case_id": case.id,
        "passed": compare.passed,
        "updated": False,
        "tiers": [
            {"name": t.name, "passed": t.passed, "messages": t.messages}
            for t in compare.tiers
        ],
        "actual_metrics": compare.actual_metrics,
        "plan_diff": compare.plan_diff,
        "messages": [],
    }


def _run_intake(args: argparse.Namespace) -> int:
    from tests.regression.intake import IntakeError, intake_debug_dump

    if not args.intake_id:
        print("--intake requires --id REG-<issue>-<slug>", file=sys.stderr)
        return 2
    try:
        case_dir = intake_debug_dump(
            Path(args.intake),
            case_id=str(args.intake_id),
            seed_anchor=args.seed_anchor,
            cycle_index=args.cycle_index,
            private=bool(args.private),
            issue=args.issue,
            title=args.title,
            force=bool(args.force),
        )
    except IntakeError as exc:
        print(f"intake failed: {exc}", file=sys.stderr)
        return 2
    print(f"Intake wrote case: {case_dir}")
    print(
        "Next: python -m scripts.run_regression --update-golden "
        f"--case {args.intake_id}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    from tests.regression.compare import CompareResult, TierResult
    from tests.regression.engine_info import engine_fingerprint
    from tests.regression.loader import load_cases, private_repo_root_from_cases
    from tests.regression.report import (
        git_sha,
        render_console_table,
        write_markdown_report,
    )

    args = _parse_args(argv)
    if args.intake is not None:
        return _run_intake(args)

    roots, skipped, private_cases = _case_roots(args)
    case_ids = set(args.case) if args.case else None
    cases = load_cases(
        *roots,
        case_ids=case_ids,
        require_expected=not (args.update_golden or args.dry_run),
    )
    if not cases:
        print("No regression cases found.", file=sys.stderr)
        if skipped:
            print(f"Skipped: {', '.join(skipped)}", file=sys.stderr)
        return 2
    if args.dry_run:
        for case in cases:
            print(f"{case.id}\t{case.level}\t{case.case_dir}")
        if skipped:
            print(f"# skipped: {', '.join(skipped)}")
        return 0

    workers = _worker_count(args.workers, len(cases))
    payloads = [
        {
            "case_dir": str(case.case_dir),
            "update_golden": bool(args.update_golden),
        }
        for case in cases
    ]
    raw_results: list[dict[str, Any]] = []
    if workers == 1 or len(payloads) == 1:
        for payload in payloads:
            raw_results.append(_run_one_case_payload(payload))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_run_one_case_payload, payload): payload
                for payload in payloads
            }
            for fut in as_completed(futures):
                raw_results.append(fut.result())

    # Stable order by case id
    raw_results.sort(key=lambda r: r["case_id"])
    compare_results: list[CompareResult] = []
    for raw in raw_results:
        tiers = [
            TierResult(name=t["name"], passed=t["passed"], messages=list(t["messages"]))
            for t in raw.get("tiers") or []
        ]
        if raw.get("updated"):
            tiers = [
                TierResult(
                    name="invariants", passed=True, messages=list(raw.get("messages") or [])
                ),
                TierResult(name="metrics", passed=True, messages=["golden rewritten"]),
                TierResult(name="plan_diff", passed=True, messages=[]),
            ]
        compare_results.append(
            CompareResult(
                case_id=raw["case_id"],
                tiers=tiers,
                actual_metrics=dict(raw.get("actual_metrics") or {}),
                plan_diff=dict(raw.get("plan_diff") or {}),
            )
        )

    print(render_console_table(compare_results))
    if skipped:
        print(f"Skipped: {', '.join(skipped)}")
    public_sha = git_sha(ROOT)
    private_root = private_repo_root_from_cases(private_cases)
    private_sha = git_sha(private_root) if private_root is not None else None
    report_path = write_markdown_report(
        Path(args.report),
        results=compare_results,
        public_sha=public_sha,
        private_sha=private_sha,
        skipped=skipped,
        engine_fingerprint=engine_fingerprint(solver_mode="strict"),
    )
    print(f"Report: {report_path}")
    if args.update_golden:
        print("Goldens updated. Commit with a justification for the behaviour change.")
        return 0
    failed = [r for r in compare_results if not r.passed]
    if failed:
        print(f"{len(failed)} case(s) failed.", file=sys.stderr)
        return 1
    print(f"All {len(compare_results)} case(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
