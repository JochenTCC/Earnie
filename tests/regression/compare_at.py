"""``run_regression --compare-at <ref>``: run cases at an older commit and at the working tree.

The older commit is checked out into a temporary git worktree next to the repo
(Windows ``MAX_PATH`` breaks recorder fixtures under deep temp dirs). Each side runs in its
own process via ``trace.py``. Output per case under
``backtesting_logs/regression/compare/<case>__<sha8>/``:

- ``base_slots.csv`` / ``head_slots.csv`` / ``diff.csv`` (L2 per-slot traces)
- ``summary.md`` (metrics, input fingerprint diff, time axis, per-series deltas)
- ``plot.html`` (Plotly overlay base vs head, L2 only)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from tests.regression.baseline import dirty_paths, git_env
from tests.regression.fingerprint import diff_inputs

TRACE_SCRIPT = Path(__file__).resolve().with_name("trace.py")
WORKTREE_ROOT_ENV = "EARNIE_COMPARE_WORKTREE_ROOT"
SLOT_DELTA_EPS = 1e-6


class CompareAtError(RuntimeError):
    """A --compare-at step failed (bad ref, worktree, trace subprocess)."""


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=str(repo), stderr=subprocess.PIPE, text=True, env=git_env()
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise CompareAtError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc


def resolve_commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def default_worktree_root(repo: Path) -> Path:
    """Sibling of the repo: short enough for MAX_PATH, never directly under a drive root."""
    raw = os.environ.get(WORKTREE_ROOT_ENV, "").strip()
    return Path(raw) if raw else repo.resolve().parent / "earnie-compare-wt"


@contextmanager
def temp_worktree(repo: Path, sha: str, root: Path, *, keep: bool) -> Iterator[Path]:
    path = root / sha[:10]
    if path.exists():
        raise CompareAtError(
            f"{path} already exists — remove it (git worktree remove --force {path}) "
            f"or set {WORKTREE_ROOT_ENV}"
        )
    root.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--detach", str(path), sha)
    try:
        yield path
    finally:
        if keep:
            print(f"worktree kept: {path}")
        else:
            _git(repo, "worktree", "remove", "--force", str(path))
            _git(repo, "worktree", "prune")


def run_trace(tree: Path, case_dir: Path, out_dir: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, str(TRACE_SCRIPT), str(tree), str(case_dir), str(out_dir)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-15:])
        raise CompareAtError(f"trace failed in {tree} for {case_dir.name}:\n{tail}")
    return json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _metrics_table(base: dict[str, Any], head: dict[str, Any]) -> list[str]:
    lines = ["| metric | base | head | Δ | Δ% |", "|---|---:|---:|---:|---:|"]
    for key in sorted(set(base) | set(head)):
        b, h = base.get(key), head.get(key)
        delta = pct = ""
        if isinstance(b, (int, float)) and isinstance(h, (int, float)):
            delta = f"{h - b:+.4f}"
            pct = f"{(h - b) / abs(b) * 100:+.2f}%" if b else ("0%" if h == b else "n/a")
        mark = " **≠**" if b != h else ""
        lines.append(f"| `{key}`{mark} | {_fmt(b)} | {_fmt(h)} | {delta} | {pct} |")
    return lines


def build_slot_diff(base: pd.DataFrame, head: pd.DataFrame) -> pd.DataFrame:
    """Outer join on timestamp: ``<col>_base``, ``<col>_head``, ``<col>_delta``."""
    columns = [c for c in base.columns if c in head.columns]
    joined = base[columns].join(head[columns], how="outer", lsuffix="_base", rsuffix="_head")
    out = pd.DataFrame(index=joined.index)
    for col in columns:
        out[f"{col}_base"] = joined[f"{col}_base"]
        out[f"{col}_head"] = joined[f"{col}_head"]
        out[f"{col}_delta"] = joined[f"{col}_head"] - joined[f"{col}_base"]
    return out


def _series_lines(diff: pd.DataFrame, base: pd.DataFrame, head: pd.DataFrame) -> list[str]:
    only_base = base.index.difference(head.index)
    only_head = head.index.difference(base.index)
    lines = [
        f"- base: {len(base)} slots, {base.index.min()} → {base.index.max()}",
        f"- head: {len(head)} slots, {head.index.min()} → {head.index.max()}",
        f"- slots only in base: {len(only_base)}, only in head: {len(only_head)}",
        "",
        "| series | slots differing (common) | max abs Δ | at | sum base | sum head |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for col in [c[: -len("_delta")] for c in diff.columns if c.endswith("_delta")]:
        delta = diff[f"{col}_delta"].dropna().abs()
        n_diff = int((delta > SLOT_DELTA_EPS).sum())
        at = str(delta.idxmax()) if n_diff else ""
        max_abs = f"{delta.max():.4f}" if len(delta) else "—"
        lines.append(
            f"| `{col}`{' **≠**' if n_diff else ''} | {n_diff}/{len(delta)} | {max_abs} | {at} "
            f"| {base[col].sum():.3f} | {head[col].sum():.3f} |"
        )
    return lines


def _write_plot(diff: pd.DataFrame, path: Path, title: str) -> str | None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return "plot skipped: plotly not installed"
    cols = [c[: -len("_delta")] for c in diff.columns if c.endswith("_delta")]
    fig = make_subplots(rows=len(cols), cols=1, shared_xaxes=True, subplot_titles=cols,
                        vertical_spacing=0.02)
    for row, col in enumerate(cols, start=1):
        for side, dash in (("base", "dot"), ("head", "solid")):
            fig.add_trace(
                go.Scatter(x=diff.index, y=diff[f"{col}_{side}"], name=f"{col} {side}",
                           line={"dash": dash}, legendgroup=side, showlegend=row == 1),
                row=row, col=1,
            )
    fig.update_layout(title=title, height=220 * len(cols), hovermode="x unified")
    fig.write_html(path, include_plotlyjs="cdn")
    return None


def write_comparison(
    *,
    case_id: str,
    base_sha: str,
    head_label: str,
    base_trace: dict[str, Any],
    head_trace: dict[str, Any],
    base_dir: Path,
    head_dir: Path,
    out_dir: Path,
) -> Path:
    lines = [
        f"# Compare `{case_id}`: `{base_sha[:8]}` → {head_label}",
        "",
        f"- level: {head_trace['level']}",
        f"- plan_hash: base `{base_trace.get('plan_hash')}` / head `{head_trace.get('plan_hash')}`",
    ]
    for side, trace in (("base", base_trace), ("head", head_trace)):
        if trace.get("pv_shape_error"):
            lines.append(f"- **PV shape guard ({side})**: {trace['pv_shape_error']}")
    lines += ["", "## Metrics", "", *_metrics_table(base_trace["metrics"], head_trace["metrics"])]

    inputs = diff_inputs(base_trace["inputs"], head_trace["inputs"])
    lines += ["", "## Inputs", ""]
    lines.append("- files changed: " + (", ".join(inputs["files"]) or "none"))
    lines.append("- effective series changed: " + (", ".join(inputs["series"]) or "none"))
    for key, (old, new) in inputs["sums"].items():
        lines.append(f"- {key}: {old} → {new}")

    if base_trace.get("slots") and head_trace.get("slots"):
        base = pd.read_csv(base_dir / "slots.csv", index_col="ts", parse_dates=True)
        head = pd.read_csv(head_dir / "slots.csv", index_col="ts", parse_dates=True)
        shutil.copyfile(base_dir / "slots.csv", out_dir / "base_slots.csv")
        shutil.copyfile(head_dir / "slots.csv", out_dir / "head_slots.csv")
        diff = build_slot_diff(base, head)
        diff.to_csv(out_dir / "diff.csv", index_label="ts")
        lines += ["", "## Per-slot series", "", *_series_lines(diff, base, head)]
        note = _write_plot(diff, out_dir / "plot.html", f"{case_id}: {base_sha[:8]} vs {head_label}")
        lines += ["", note or "Plot: `plot.html` (base dotted, head solid)."]
    else:
        lines += ["", "No per-slot trace for this level (L1 replay exposes slot 0 only)."]

    summary = out_dir / "summary.md"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def compare_cases_at(
    *,
    repo: Path,
    ref: str,
    case_dirs: list[Path],
    out_root: Path,
    worktree_root: Path,
    keep_worktree: bool,
) -> list[Path]:
    base_sha = resolve_commit(repo, ref)
    head_sha = resolve_commit(repo, "HEAD")
    dirty = dirty_paths(repo)
    head_label = f"`{head_sha[:8]}`" + (" + uncommitted changes" if dirty else "")
    summaries: list[Path] = []
    with temp_worktree(repo, base_sha, worktree_root, keep=keep_worktree) as base_tree:
        for case_dir in case_dirs:
            out_dir = out_root / f"{case_dir.name}__{base_sha[:8]}"
            if out_dir.exists():
                shutil.rmtree(out_dir)
            base_dir, head_dir = out_dir / "_base", out_dir / "_head"
            print(f"{case_dir.name}: tracing base {base_sha[:8]} …")
            base_trace = run_trace(base_tree, case_dir, base_dir)
            print(f"{case_dir.name}: tracing head …")
            head_trace = run_trace(repo, case_dir, head_dir)
            summaries.append(
                write_comparison(
                    case_id=case_dir.name,
                    base_sha=base_sha,
                    head_label=head_label,
                    base_trace=base_trace,
                    head_trace=head_trace,
                    base_dir=base_dir,
                    head_dir=head_dir,
                    out_dir=out_dir,
                )
            )
    return summaries
