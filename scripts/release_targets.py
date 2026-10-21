"""Read the release ``targets`` from an annotated version tag (release-publish.yml).

A tag push cannot carry workflow inputs, so the publish scope travels in the tag
message as its own line::

    git tag -a v2.7.0 -m "Release v2.7.0" -m "targets: ha"

Allowed values: ``both`` | ``docker`` (LoxBerry/Synology :next/:latest) | ``ha``
(HA add-on). There is no default: a lightweight tag, a missing line or several
``targets:`` lines fail the release before anything is built.

  python -m scripts.release_targets --tag v2.7.0     # prints the targets value
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

TARGETS = ("both", "docker", "ha")
_LINE_RE = re.compile(r"^\s*targets\s*:\s*(\S*)\s*$", re.IGNORECASE | re.MULTILINE)


class ReleaseTargetsError(ValueError):
    """Tag message does not state exactly one valid ``targets:`` line."""


def parse_targets(message: str, *, tag: str = "tag") -> str:
    """Return the single ``targets:`` value of *message*."""
    found = [m.group(1).lower() for m in _LINE_RE.finditer(message)]
    if not found:
        raise ReleaseTargetsError(
            f"{tag}: tag message has no 'targets: both|docker|ha' line — "
            "re-create the tag via skill session-abschluss or start Release via Run workflow"
        )
    if len(found) > 1:
        raise ReleaseTargetsError(f"{tag}: several targets lines in tag message: {found}")
    value = found[0]
    if value not in TARGETS:
        raise ReleaseTargetsError(f"{tag}: unknown targets {value!r} (both | docker | ha)")
    return value


def _git(*args: str) -> str:
    proc = subprocess.run(  # NOSONAR pythonsecurity:S8705 — fixed git argv
        ["git", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise ReleaseTargetsError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def tag_message(tag: str) -> str:
    """Message of annotated *tag*; lightweight tags are rejected (they have none)."""
    ref = f"refs/tags/{tag}"
    if _git("cat-file", "-t", ref).strip() != "tag":
        raise ReleaseTargetsError(
            f"{tag} is a lightweight tag — use an annotated tag with a 'targets:' line"
        )
    return _git("for-each-ref", "--format=%(contents)", ref)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="Annotated tag, e.g. v2.7.0-alpha.3")
    args = parser.parse_args(argv)
    try:
        print(parse_targets(tag_message(args.tag), tag=args.tag))
    except ReleaseTargetsError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
