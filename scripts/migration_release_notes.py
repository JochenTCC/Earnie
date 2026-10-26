"""Draft the German release-notes ## Migration section from the registry.

Usage:
  python -m scripts.migration_release_notes --since <tag-or-commit>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from runtime_store.migration.registry import STEPS
from runtime_store.migration.types import MigrationStep

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REGISTRY_REL = "runtime_store/migration/registry.py"
_STEP_ID_RE = re.compile(
    r'^\s*(?:STEP_ID\s*=\s*|id\s*=\s*)["\']([^"\']+)["\']',
    re.MULTILINE,
)


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def step_ids_from_source(source: str) -> frozenset[str]:
    """Extract step id string literals from registry or step module source."""
    return frozenset(_STEP_ID_RE.findall(source))


def _git_rev_exists(rev: str, *, repo: Path = _REPO_ROOT) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{rev}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode == 0


def git_show(rev: str, rel_path: str, *, repo: Path = _REPO_ROOT) -> str | None:
    """Return file contents at ``rev``, or None if the path is absent at that rev.

    Raises ValueError when ``rev`` itself is unknown or git fails for another reason.
    """
    result = subprocess.run(
        ["git", "show", f"{rev}:{rel_path}"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    err = (result.stderr or result.stdout or "").strip()
    if "does not exist in" in err or "exists on disk, but not in" in err:
        return None
    if not _git_rev_exists(rev, repo=repo):
        raise ValueError(f"unknown git revision: {rev}")
    raise ValueError(
        f"git show {rev}:{rel_path} failed"
        + (f": {err}" if err else f" (exit {result.returncode})")
    )


def previous_step_ids(since: str, *, repo: Path = _REPO_ROOT) -> frozenset[str]:
    """Step ids known at ``since``.

    If the migration package did not exist yet, returns an empty set (all current
    steps are treated as new). Unknown ``since`` fails loud.
    """
    if not _git_rev_exists(since, repo=repo):
        raise ValueError(f"unknown git revision: {since}")

    source = git_show(since, _REGISTRY_REL, repo=repo)
    if source is None:
        return frozenset()

    ids = step_ids_from_source(source)
    if ids:
        return ids

    # Registry only imports STEP objects; collect STEP_ID from step modules.
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", since, "runtime_store/migration/steps"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if listed.returncode != 0 or not listed.stdout.strip():
        return frozenset()

    collected: set[str] = set()
    for line in listed.stdout.splitlines():
        path = line.strip()
        if not path.endswith(".py") or path.endswith("__init__.py"):
            continue
        module_src = git_show(since, path, repo=repo)
        if module_src is None:
            continue
        collected |= set(step_ids_from_source(module_src))
    return frozenset(collected)


def new_steps(
    current: tuple[MigrationStep, ...],
    previous_ids: frozenset[str],
) -> tuple[MigrationStep, ...]:
    """Return current steps whose id was not in ``previous_ids`` (registry order)."""
    return tuple(step for step in current if step.id not in previous_ids)


def format_migration_section(steps: tuple[MigrationStep, ...]) -> str:
    """German markdown ## Migration draft for release notes."""
    lines = [
        "## Migration",
        "",
        "Nach dem Update kann Earnie eine **Konfigurationsmigration** verlangen "
        "(Streamlit-Assistent). Der Optimierer-Dienst startet erst danach.",
        "",
        "- **Backup:** unter dem Config-Verzeichnis "
        "`backups/pre-migration-dm…-<Zeitstempel>/` "
        "(inkl. `manifest.json` und `report.json`). Alte Backups bleiben liegen; "
        "löschen nur manuell.",
        "- **Kein Downgrade:** eine ältere Earnie-Version lehnt ein neueres "
        "Datenmodell ab. Rückweg nur durch manuelles Wiederherstellen des Backups.",
        "",
    ]
    if not steps:
        lines.extend(
            [
                "_Keine neuen Migrationsschritte seit dem angegebenen Stand "
                "(Registry unverändert)._",
                "",
            ]
        )
        return "\n".join(lines)

    lines.append("### Neue Schritte in dieser Version")
    lines.append("")
    for step in steps:
        files = ", ".join(f"`{name}`" for name in step.files)
        lines.append(f"- **`{step.id}`** — {step.title_de}")
        lines.append(f"  - Dateien: {files}")
        if step.questions:
            for question in step.questions:
                req = "pflicht" if question.required else "optional"
                lines.append(
                    f"  - Frage ({req}): {question.prompt_de} (`{question.id}`)"
                )
        if step.questions_for is not None:
            lines.append(
                "  - Weitere Fragen je nach Konfiguration (pro Hausprofil / Tarif, "
                "werden beim Migrieren aus der Config berechnet)."
            )
        if not step.questions and step.questions_for is None:
            lines.append("  - Keine Wizard-Fragen (nur Erkennung / Apply).")
        lines.append(
            "  - Manuelle To-dos: werden beim Migrieren aus der Config berechnet "
            "(nicht fest in der Registry)."
        )
        lines.append("")
    return "\n".join(lines)


def build_section(since: str, *, repo: Path = _REPO_ROOT) -> str:
    prev = previous_step_ids(since, repo=repo)
    return format_migration_section(new_steps(STEPS, prev))


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--since",
        required=True,
        help="Git tag or commit to diff registry step ids against",
    )
    args = parser.parse_args(argv)
    try:
        print(build_section(args.since), end="")
    except ValueError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
