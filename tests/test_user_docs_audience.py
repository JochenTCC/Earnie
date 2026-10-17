"""User docs must not describe [dev] features (spec release-notes-workflow section 8)."""
from __future__ import annotations

from pathlib import Path

from scripts.release_notes_collect import load_audience_config

_ROOT = Path(__file__).resolve().parents[1]


def _user_doc_files(cfg: dict) -> list[Path]:
    files: list[Path] = []
    for rel in cfg["user_doc_paths"]:
        path = _ROOT / rel
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    excluded = {_ROOT / rel for rel in cfg.get("user_doc_exclude", [])}
    return [f for f in files if f not in excluded]


def test_user_docs_do_not_mention_dev_terms_beyond_baseline():
    cfg = load_audience_config()
    allow = set(cfg["docs_allowlist"])
    terms = [t.lower() for t in cfg["dev_terms"]]
    offenders = {}
    for path in _user_doc_files(cfg):
        rel = path.relative_to(_ROOT).as_posix()
        text = path.read_text(encoding="utf-8").lower()
        hits = sorted(t for t in terms if t in text)
        if hits and rel not in allow:
            offenders[rel] = hits
    assert not offenders, f"[dev] terms in user docs (move to docs/entwicklung/ or docs/dev/): {offenders}"


def test_allowlist_only_contains_files_that_still_violate():
    """Ratchet: remove an entry as soon as its file is clean."""
    cfg = load_audience_config()
    terms = [t.lower() for t in cfg["dev_terms"]]
    stale = [
        rel
        for rel in cfg["docs_allowlist"]
        if not any(t in (_ROOT / rel).read_text(encoding="utf-8").lower() for t in terms)
    ]
    assert not stale, f"clean files still in docs_allowlist, remove: {stale}"


def _id_counts(cfg: dict) -> dict[str, int]:
    import re

    from scripts.release_notes_collect import BACKLOG_ID_RE

    counts = {}
    for path in _user_doc_files(cfg):
        text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
        n = len(BACKLOG_ID_RE.findall(text))
        if n:
            counts[path.relative_to(_ROOT).as_posix()] = n
    return counts


def test_user_docs_do_not_gain_backlog_version_ids():
    """Internal chapter IDs (2.7.n, 2.+1) confuse readers; counts may only shrink."""
    cfg = load_audience_config()
    base = cfg["backlog_id_baseline"]
    grown = {f: (n, base.get(f, 0)) for f, n in _id_counts(cfg).items() if n > base.get(f, 0)}
    assert not grown, f"new backlog version IDs in user docs (file: found, allowed): {grown}"


def test_backlog_id_baseline_is_tight():
    """Ratchet: lower/delete the baseline entry once IDs were removed from a doc."""
    cfg = load_audience_config()
    counts = _id_counts(cfg)
    loose = {f: (n, counts.get(f, 0)) for f, n in cfg["backlog_id_baseline"].items() if n > counts.get(f, 0)}
    assert not loose, f"baseline too high (file: baseline, actual) - lower it: {loose}"
