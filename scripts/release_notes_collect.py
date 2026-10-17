"""Collect the evidence pack for release notes (changes since the last productive release).

Usage:
  python -m scripts.release_notes_collect [--since auto|<tag>] [--target <version>]

Deterministic, no LLM. Refuses -dev versions. Output stays local (backtesting_logs/).
Spec: docs/workflow/release-notes-workflow.md
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _REPO_ROOT / "backtesting_logs" / "release_notes"
_PRODUCTIVE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_TARGET_RE = re.compile(r"^\d+\.\d+\.\d+(?:-(alpha|beta|rc|dev)\.\d+)?$")
_ERLEDIGT_HEADING_RE = re.compile(r"^###\s+(.*)\((\d{4}-\d{2}-\d{2})\)\s*$")
_ISSUE_RE = re.compile(r"(?<![\w/])#(\d+)\b")
_PREFIX_RE = re.compile(r"^([a-zA-Z0-9_\-]+)(?:\(([^)]*)\))?:")
_NOISE_PREFIXES = frozenset({"backlog", "merge"})
_AUDIENCE_RE = re.compile(r"\[(feat|qual|dev)\]")
# Internal backlog version chapters (2.7.n, 2.6.a, 2.+1) — never shown to readers.
BACKLOG_ID_RE = re.compile(r"\b[1-3]\.\d+\.[a-z]\b|\b\d+\.\+\d+\b")


def find_backlog_ids(text: str) -> list[str]:
    """Internal backlog version IDs in the *visible* text (HTML comments are ignored)."""
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return sorted(set(BACKLOG_ID_RE.findall(visible)))
_ENTRY_RE = re.compile(r"^- \[[ xX]\] (.*)$")
_AUDIENCE_TOML = _REPO_ROOT / ".github" / "release-notes" / "audience.toml"

STRUCTURAL_DIRS = (
    "runtime_store/migration/",
    "house_config/",
    "settings/",
    "share/config/",
)
USER_DOC_DIRS = ("docs/user-manual/", "docs/einrichtung/", "docs/konfiguration/")
PLATFORM_PATHS: dict[str, tuple[str, ...]] = {
    "Home Assistant": ("packaging/homeassistant-addon/", "integrations/ha_"),
    "LoxBerry / Loxone": ("packaging/loxberry", "integrations/loxone"),
    "Synology / Docker": ("docker/compose/synology", "docker/"),
    "Proxmox": ("docker/compose/proxmox", "scripts/qemu"),
}


def _configure_console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _git(*args: str, repo: Path = _REPO_ROOT) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}"
        )
    return result.stdout


def channel_of(version: str) -> str:
    """``official`` | ``pre-release``; ``-dev`` is rejected (no notes for dev)."""
    if not _TARGET_RE.match(version):
        raise ValueError(f"unrecognized version string: {version!r}")
    if "-dev." in version:
        raise ValueError(
            f"{version}: no release notes for -dev versions (see release-notes.mdc)"
        )
    return "pre-release" if "-" in version else "official"


def current_version(repo: Path = _REPO_ROOT) -> str:
    text = (repo / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError("__version__ not found in version.py")
    # Strip temporary debug suffix (e.g. -dev.48D1) like version.normalize_for_image_build.
    return re.sub(r"^(\d+\.\d+\.\d+(?:-(?:alpha|beta|rc|dev)\.\d+)?).*$", r"\1", match.group(1))


def published_release_tags(repo: Path = _REPO_ROOT) -> frozenset[str]:
    """Tags with a published (non-draft) GitHub Release. Fails loud without ``gh``."""
    try:
        result = subprocess.run(
            ["gh", "release", "list", "--limit", "200", "--json", "tagName,isDraft"],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "GitHub CLI 'gh' not found: needed to tell published releases from declined "
            "candidates. Install/authenticate gh, or pass --since <tag> explicitly."
        ) from exc
    if result.returncode != 0:
        raise ValueError(
            f"gh release list failed: {(result.stderr or result.stdout).strip()} "
            "(authenticate with 'gh auth login' or pass --since <tag>)"
        )
    return frozenset(
        r["tagName"] for r in json.loads(result.stdout) if not r.get("isDraft")
    )


def pick_baseline(tags_merged: list[str], published: frozenset[str]) -> str:
    """Newest productive tag among tags merged into HEAD (input newest first) that
    also has a published GitHub Release (declined candidates stay drafts)."""
    for tag in tags_merged:
        if _PRODUCTIVE_TAG_RE.match(tag) and tag in published:
            return tag
    raise ValueError(
        "no published productive vX.Y.Z release is an ancestor of HEAD"
    )


def find_baseline(repo: Path = _REPO_ROOT) -> str:
    out = _git("tag", "--merged", "HEAD", "--sort=-creatordate", repo=repo)
    return pick_baseline(
        [t.strip() for t in out.splitlines() if t.strip()],
        published_release_tags(repo),
    )


def unmerged_productive_tags(repo: Path = _REPO_ROOT) -> list[str]:
    """Productive tags NOT reachable from HEAD (released on a hotfix branch)."""
    all_tags = _git("tag", "--list", "v*", "--sort=-creatordate", repo=repo).split()
    merged = set(_git("tag", "--merged", "HEAD", repo=repo).split())
    return [t for t in all_tags if _PRODUCTIVE_TAG_RE.match(t) and t not in merged]


def load_audience_config(path: Path = _AUDIENCE_TOML) -> dict:
    """Pre-classification config; fails loud when missing or incomplete."""
    if not path.is_file():
        raise ValueError(f"audience config missing: {path}")
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("dev_prefixes", "dev_terms"):
        if not isinstance(cfg.get(key), list):
            raise ValueError(f"{path.name}: '{key}' must be a list")
    return cfg


def classify_entry(text: str, section_title: str, cfg: dict) -> dict:
    """Audience of one backlog entry (first line ``text``).

    Explicit marker wins. Bugfix sections/entries count as ``fix``. Everything else is
    ``unmarked`` with a ``suggestion`` from ``dev_terms`` (never auto-decided).
    """
    marker = _AUDIENCE_RE.search(text)
    if marker:
        return {"audience": marker.group(1), "suggestion": None}
    if re.match(r"(?i)\s*(\*\*)?bugfix\b", text) or re.match(r"(?i)bugfix\b", section_title):
        return {"audience": "fix", "suggestion": None}
    haystack = f"{section_title} {text}".lower()
    hit = any(term.lower() in haystack for term in cfg["dev_terms"])
    return {"audience": "unmarked", "suggestion": "dev" if hit else None}


def classify_subject(subject: str) -> str:
    """Group key for a commit subject: its prefix, ``merge`` or ``other``."""
    if subject.startswith("Merge "):
        return "merge"
    match = _PREFIX_RE.match(subject)
    return match.group(1).lower() if match else "other"


def group_commits(commits: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Split commits into (groups by prefix, noise). Dev groups are split at render time."""
    groups: dict[str, list[dict]] = defaultdict(list)
    noise: list[dict] = []
    for commit in commits:
        key = classify_subject(commit["subject"])
        if key in _NOISE_PREFIXES:
            noise.append(commit)
        else:
            groups[key].append(commit)
    return dict(groups), noise


def parse_erledigt(text: str, since: date, cfg: dict | None = None) -> list[dict]:
    """Archive sections whose heading date is on/after ``since``.

    Each section has ``title``, ``date``, ``body`` and (when ``cfg`` is given) ``entries``:
    top-level checkbox lines with their audience classification.
    """
    sections: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        heading = _ERLEDIGT_HEADING_RE.match(line)
        if heading:
            current = None
            if date.fromisoformat(heading.group(2)) >= since:
                current = {
                    "title": heading.group(1).strip(),
                    "date": heading.group(2),
                    "body": [],
                }
                sections.append(current)
        elif current is not None:
            current["body"].append(line)
    for section in sections:
        lines = section["body"]
        section["body"] = "\n".join(lines).strip()
        if cfg is not None:
            section["entries"] = [
                {"text": m.group(1)[:200], **classify_entry(m.group(1), section["title"], cfg)}
                for m in (_ENTRY_RE.match(ln) for ln in lines)
                if m
            ]
    return sections


def classify_paths(paths: list[str]) -> dict:
    structural = sorted(p for p in paths if p.startswith(STRUCTURAL_DIRS))
    user_docs = sorted(p for p in paths if p.startswith(USER_DOC_DIRS))
    platforms: dict[str, list[str]] = {}
    for name, prefixes in PLATFORM_PATHS.items():
        hit = sorted(p for p in paths if p.startswith(prefixes))
        if hit:
            platforms[name] = hit
    return {"structural": structural, "user_docs": user_docs, "platforms": platforms}


def verifications_pending(text: str) -> str:
    match = re.search(
        r"^## Bugfix Verifications Pending\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M
    )
    return match.group(1).strip() if match else ""


def migration_section(baseline: str, repo: Path = _REPO_ROOT) -> str:
    """German ``## Migration`` draft for steps new between ``baseline`` and ``HEAD`` of ``repo``."""
    from runtime_store.migration.registry import STEPS
    from scripts.migration_release_notes import (
        format_migration_section,
        previous_step_ids,
    )

    new_ids = previous_step_ids("HEAD", repo=repo) - previous_step_ids(baseline, repo=repo)
    known = {step.id: step for step in STEPS}
    missing = sorted(new_ids - known.keys())
    if missing:
        raise ValueError(
            f"migration steps at HEAD of {repo} not importable from the running tree: "
            f"{', '.join(missing)} (run the script from that checkout)"
        )
    return format_migration_section(tuple(s for s in STEPS if s.id in new_ids))


def collect(since: str, target: str, repo: Path = _REPO_ROOT) -> dict:
    channel = channel_of(target)
    baseline = find_baseline(repo) if since == "auto" else since
    base_date = _git("log", "-1", "--format=%cI", baseline, repo=repo).strip()[:10]
    head = _git("rev-parse", "--short", "HEAD", repo=repo).strip()

    raw = _git("log", "--format=%h%x1f%s", f"{baseline}..HEAD", repo=repo)
    commits = []
    for line in raw.splitlines():
        sha, _, subject = line.partition("\x1f")
        commits.append(
            {"sha": sha, "subject": subject, "issues": _ISSUE_RE.findall(subject)}
        )
    groups, noise = group_commits(commits)

    changed = [
        p
        for p in _git("diff", "--name-only", f"{baseline}..HEAD", repo=repo).splitlines()
        if p
    ]

    def _read(rel: str) -> str:
        path = repo / rel
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    migration = migration_section(baseline, repo)
    cfg = load_audience_config(repo / ".github" / "release-notes" / "audience.toml")

    unreleased = _read(".github/release-notes/UNRELEASED.md")
    regression = _read("backtesting_logs/regression/regression_report.md")
    return {
        "audience_config": cfg,
        "target": target,
        "channel": channel,
        "baseline": baseline,
        "baseline_date": base_date,
        "head": head,
        "unmerged_productive_tags": unmerged_productive_tags(repo),
        "commit_count": len(commits),
        "commit_groups": groups,
        "noise_commits": noise,
        "archived_items": parse_erledigt(
            _read("backlog/Backlog-Erledigt.md"), date.fromisoformat(base_date), cfg
        ),
        "paths": classify_paths(changed),
        "migration_section": migration,
        "unreleased_notes": unreleased,
        "regression_report_head": "\n".join(regression.splitlines()[:40]),
        "verifications_pending": verifications_pending(
            _read("backlog/Backlog-Bugfixes.md")
        ),
    }


def _entry_line(entry: dict) -> str:
    hint = f" (suggestion: {entry['suggestion']})" if entry.get("suggestion") else ""
    return f"- [{entry['audience']}] {entry['text']}{hint}"


def render_markdown(ev: dict) -> str:
    unmerged = ev["unmerged_productive_tags"]
    out = [
        f"# Release-notes evidence — {ev['target']} ({ev['channel']})",
        "",
        f"Baseline: `{ev['baseline']}` ({ev['baseline_date']}) → HEAD `{ev['head']}`, "
        f"{ev['commit_count']} commits.",
        "",
        *(
            [
                f"> WARNING: productive tags not merged into HEAD: {', '.join(unmerged)}. "
                "Their fixes may already be released; check their notes in "
                "`.github/release-notes/` and do not announce them as new.",
                "",
            ]
            if unmerged
            else []
        ),
        "## Maintainer hints (UNRELEASED.md — must appear in the draft)",
        "",
        ev["unreleased_notes"].strip() or "_empty_",
        "",
        "## Archived backlog items since baseline (primary wording source)",
        "",
    ]
    out += [
        "Audience per entry: `feat` = feature, `qual` = quality (one short line), "
        "`fix` = bugfix, `dev` = internal (see last section), "
        "`unmarked` = ask the maintainer.",
        "",
    ]
    for item in ev["archived_items"]:
        entries = item.get("entries", [])
        if entries and all(e["audience"] == "dev" for e in entries):
            continue  # listed under "Internal" below
        out += [f"### {item['title']} ({item['date']})", ""]
        out += [_entry_line(e) for e in entries if e["audience"] != "dev"]
        out += ["", item["body"], ""]
    if not ev["archived_items"]:
        out += ["_none_", ""]
    unmarked = [e for i in ev["archived_items"] for e in i.get("entries", []) if e["audience"] == "unmarked"]
    out += [f"## Unmarked entries — ASK the maintainer ({len(unmarked)})", ""]
    out += [_entry_line(e) for e in unmarked] or ["_none_"]
    out.append("")
    dev_prefixes = set(ev["audience_config"]["dev_prefixes"])
    public_groups = {k: v for k, v in ev["commit_groups"].items() if k not in dev_prefixes}
    internal_groups = {k: v for k, v in ev["commit_groups"].items() if k in dev_prefixes}
    out += ["## Commits by prefix (public candidates)", ""]
    for key in sorted(public_groups, key=lambda k: -len(public_groups[k])):
        out.append(f"### {key} ({len(public_groups[key])})")
        out += [f"- `{c['sha']}` {c['subject']}" for c in public_groups[key]]
        out.append("")
    out.append(f"_{len(ev['noise_commits'])} merge/backlog-only commits omitted._")
    out += ["", "## Data model / config", "", ev["migration_section"], ""]
    paths = ev["paths"]
    out += ["Structural files changed:", ""]
    out += [f"- `{p}`" for p in paths["structural"]] or ["_none_"]
    out += ["", "## User-facing docs touched", ""]
    out += [f"- `{p}`" for p in paths["user_docs"]] or ["_none_"]
    out += ["", "## Platform impact (heuristic — confirm)", ""]
    for name, files in paths["platforms"].items():
        out.append(f"- **{name}**: {len(files)} files (e.g. `{files[0]}`)")
    if not paths["platforms"]:
        out.append("_none_")
    out += ["", "## Open bugfix verifications (known-issue candidates)", ""]
    out += [ev["verifications_pending"] or "_none_", ""]
    if ev["regression_report_head"]:
        out += ["## Regression report (head)", "", ev["regression_report_head"], ""]
    internal_items = [
        e for i in ev["archived_items"] for e in i.get("entries", []) if e["audience"] == "dev"
    ]
    out += [
        "## Internal — DO NOT OUTPUT in release notes or user docs",
        "",
        "Listed only so you know what to leave out.",
        "",
    ]
    out += [_entry_line(e) for e in internal_items]
    out += [f"- commits `{key}`: {len(commits)}" for key, commits in internal_groups.items()]
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="auto", help="auto (last productive tag) or tag/commit")
    parser.add_argument("--target", help="target version (default: version.py)")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        target = args.target or current_version()
        evidence = collect(args.since, target)
    except ValueError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "release_notes_evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    md_path = args.out / "release_notes_evidence.md"
    md_path.write_text(render_markdown(evidence), encoding="utf-8")
    print(f"Evidence pack: {md_path} (baseline {evidence['baseline']}, "
          f"{evidence['commit_count']} commits, target {target})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
