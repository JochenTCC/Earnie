"""Promote a reviewed release-notes draft to .github/release-notes/v<version>.md.

Usage:
  python -m scripts.release_notes_finalize --version <version> --approved
  python -m scripts.release_notes_finalize --version <version> --check   # CI gate

``--approved`` may only be passed after the maintainer explicitly approved the draft
for this version in chat (rule release-notes.mdc). Spec: docs/workflow/release-notes-workflow.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from scripts.release_notes_collect import channel_of, find_backlog_ids

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NOTES_REL = Path(".github/release-notes")
_STATUS_RE = re.compile(r"<!--\s*status:\s*DRAFT.*?-->\s*\n?", re.S)
_REVIEW_RE = re.compile(r"<!--\s*REVIEW:.*?-->", re.S)
_SRC_RE = re.compile(r"[ \t]*<!--\s*src:.*?-->", re.S)


def finalize_text(draft: str, *, approved: bool) -> str:
    """Return the final notes text, or raise ValueError when the draft is not releasable."""
    if _REVIEW_RE.search(draft):
        raise ValueError(
            f"{len(_REVIEW_RE.findall(draft))} unresolved <!-- REVIEW: --> marker(s) in draft"
        )
    if _STATUS_RE.search(draft) and not approved:
        raise ValueError("draft still has 'status: DRAFT' and --approved was not given")
    text = _SRC_RE.sub("", _STATUS_RE.sub("", draft))
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    if not text.lstrip().startswith("## "):
        raise ValueError("final notes must start with '## Earnie <version>'")
    _reject_backlog_ids(text)
    return text


def _reject_backlog_ids(text: str) -> None:
    ids = find_backlog_ids(text)
    if ids:
        raise ValueError(
            f"internal backlog version IDs in visible text: {', '.join(ids)} "
            "(remove them; keep IDs only in <!-- src: --> comments)"
        )


def reset_unreleased(text: str) -> str:
    """Keep only the header (everything before the first '## ' section)."""
    head, sep, _ = text.partition("\n## ")
    return head.rstrip() + "\n" if sep else text


def finalize(version: str, *, approved: bool, repo: Path = _REPO_ROOT) -> Path:
    channel = channel_of(version)  # rejects -dev and garbage
    notes_dir = repo / _NOTES_REL
    draft_path = notes_dir / "drafts" / f"v{version}.draft.md"
    final_path = notes_dir / f"v{version}.md"
    if not draft_path.is_file():
        raise ValueError(f"draft not found: {draft_path}")
    if final_path.exists():
        raise ValueError(f"{final_path.name} already exists; refusing to overwrite")
    final = finalize_text(draft_path.read_text(encoding="utf-8"), approved=approved)
    final_path.write_text(final, encoding="utf-8")
    draft_path.unlink()
    if channel == "official":
        unreleased = notes_dir / "UNRELEASED.md"
        if unreleased.is_file():
            unreleased.write_text(
                reset_unreleased(unreleased.read_text(encoding="utf-8")), encoding="utf-8"
            )
    return final_path


def check_final(version: str, *, repo: Path = _REPO_ROOT) -> Path:
    """CI gate: reviewed final notes must exist for a non-dev version."""
    channel_of(version)
    path = repo / _NOTES_REL / f"v{version}.md"
    if not path.is_file():
        raise ValueError(
            f"missing {path.relative_to(repo)} — create it via skill release-notes "
            "(draft -> maintainer review -> release_notes_finalize)"
        )
    text = path.read_text(encoding="utf-8")
    if _STATUS_RE.search(text) or _REVIEW_RE.search(text):
        raise ValueError(f"{path.name} still contains DRAFT/REVIEW markers (unreviewed)")
    if not text.lstrip().startswith("## "):
        raise ValueError(f"{path.name} must start with '## Earnie <version>'")
    _reject_backlog_ids(text)
    return path


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--approved",
        action="store_true",
        help="maintainer explicitly approved this draft in chat",
    )
    parser.add_argument("--check", action="store_true", help="only verify final notes (CI)")
    args = parser.parse_args(argv)
    try:
        if args.check:
            print(f"Release notes OK: {check_final(args.version)}")
            return 0
        path = finalize(args.version, approved=args.approved)
    except ValueError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 2
    print(f"Release notes written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
