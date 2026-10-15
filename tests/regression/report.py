"""Console table + markdown regression report."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.regression.compare import CompareResult


def git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def render_console_table(results: list[CompareResult]) -> str:
    lines = [
        f"{'CASE':<40} {'OK':<4} {'INVAR':<6} {'METRICS':<8} {'PLAN'}",
        "-" * 80,
    ]
    for result in results:
        by_name = {t.name: t for t in result.tiers}
        inv = "PASS" if by_name.get("invariants", _fail()).passed else "FAIL"
        met = "PASS" if by_name.get("metrics", _fail()).passed else "FAIL"
        plan = "info"
        if result.plan_diff.get("hash_changed"):
            plan = "diff"
        ok = "Y" if result.passed else "N"
        lines.append(f"{result.case_id:<40} {ok:<4} {inv:<6} {met:<8} {plan}")
    return "\n".join(lines)


def write_markdown_report(
    path: Path,
    *,
    results: list[CompareResult],
    public_sha: str,
    engine_fingerprint: dict[str, Any] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    passed = sum(1 for r in results if r.passed)
    lines = [
        "# Regression report",
        "",
        f"- Generated: `{now}`",
        f"- Public SHA: `{public_sha}`",
        f"- Cases: {passed}/{len(results)} passed",
        "",
    ]
    if engine_fingerprint:
        lines.append("## Engine fingerprint")
        lines.append("")
        for key, value in engine_fingerprint.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    lines.append("## Cases")
    lines.append("")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"### `{result.case_id}` — {status}")
        lines.append("")
        for tier in result.tiers:
            mark = "ok" if tier.passed else "FAIL"
            lines.append(f"- **{tier.name}**: {mark}")
            for msg in tier.messages:
                lines.append(f"  - {msg}")
        if result.actual_metrics:
            lines.append("- metrics:")
            for key, value in sorted(result.actual_metrics.items()):
                lines.append(f"  - `{key}`: `{value}`")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _fail():
    from tests.regression.compare import TierResult

    return TierResult(name="missing", passed=False, messages=["tier missing"])
