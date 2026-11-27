"""Cognitive complexity check, same metric and scope as SonarCloud rule ``python:S3776``.

The quality gate (skill ``quality-gate``) and SonarCloud measure function complexity
the same way: SonarSource cognitive complexity, limit 15. ``complexipy`` implements
that metric locally (dev extra). The scope is read from ``sonar-project.properties``
so both cannot drift apart:

- files in ``sonar.exclusions`` are skipped, except ``data/`` and ``runtime_store/``:
  Sonar does not analyse them, the quality gate does (``MEASURED_DESPITE_SONAR``);
- files matched by a ``sonar.issue.ignore.multicriteria`` entry for ``python:S3776``
  are skipped (``scripts/``, ``studies/``, ``tools/``).

Suppressions in code are not supported: mark a false positive in SonarCloud instead.

  python -m scripts.check_cognitive_complexity                # list everything over 15
  python -m scripts.check_cognitive_complexity --max 30       # gate: nothing over 30
  python -m scripts.check_cognitive_complexity optimizer ui   # only these paths

Exit code 1 when a function is over ``--max``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SONAR_PROPERTIES = REPO_ROOT / "sonar-project.properties"
RULE_KEY = "python:S3776"
DEFAULT_MAX = 15
# Sonar excludes these from analysis; the quality gate still measures them.
MEASURED_DESPITE_SONAR = ("**/runtime_store/**", "**/data/**")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    name: str
    complexity: int


def read_properties(text: str) -> dict[str, str]:
    """Java ``.properties`` subset used by ``sonar-project.properties`` (``\\`` continuations)."""
    props: dict[str, str] = {}
    logical: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not logical and (not line or line.startswith(("#", "!"))):
            continue
        if line.endswith("\\"):
            logical.append(line[:-1].strip())
            continue
        logical.append(line)
        joined = "".join(logical)
        logical = []
        key, sep, value = joined.partition("=")
        if not sep:
            raise ValueError(f"sonar-project.properties: no '=' in {joined!r}")
        props[key.strip()] = value.strip()
    return props


def excluded_patterns(props: dict[str, str]) -> tuple[str, ...]:
    """Sonar patterns whose files this check skips (see module docstring)."""
    analysis = [p.strip() for p in props.get("sonar.exclusions", "").split(",") if p.strip()]
    patterns = [p for p in analysis if p not in MEASURED_DESPITE_SONAR]
    prefix = "sonar.issue.ignore.multicriteria"
    for entry in (e.strip() for e in props.get(prefix, "").split(",") if e.strip()):
        if props.get(f"{prefix}.{entry}.ruleKey") == RULE_KEY:
            resource = props.get(f"{prefix}.{entry}.resourceKey")
            if not resource:
                raise ValueError(f"{prefix}.{entry} has no resourceKey")
            patterns.append(resource)
    return tuple(patterns)


def sonar_glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Sonar wildcard: ``**`` any number of folders, ``*`` within one name, ``?`` one char."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def in_scope(path: str, patterns: tuple[str, ...]) -> bool:
    return not any(sonar_glob_to_regex(p).match(path) for p in patterns)


def tracked_python_files(paths: list[str]) -> list[str]:
    proc = subprocess.run(  # NOSONAR pythonsecurity:S8705 — fixed git argv
        ["git", "ls-files", "--", *(paths or ["."])],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return sorted(p for p in proc.stdout.splitlines() if p.endswith(".py"))


def measure(files: list[str], root: Path = REPO_ROOT) -> list[Finding]:
    import complexipy

    findings = []
    for rel in files:
        result = complexipy.file_complexity(str(root / rel), with_plans=False)
        findings.extend(
            Finding(rel, fn.line_start, fn.name, fn.complexity) for fn in result.functions
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="limit to these files or folders")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help="allowed complexity")
    args = parser.parse_args(argv)

    patterns = excluded_patterns(read_properties(SONAR_PROPERTIES.read_text(encoding="utf-8")))
    files = [f for f in tracked_python_files(args.paths) if in_scope(f, patterns)]
    over = sorted(
        (f for f in measure(files) if f.complexity > args.max),
        key=lambda f: (-f.complexity, f.path, f.line),
    )
    for f in over:
        print(f"{f.complexity:4d}  {f.path}:{f.line}  {f.name}")
    print(f"{len(over)} function(s) over {args.max} in {len(files)} file(s)")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
