"""Idempotent release builds: decide whether a ``:<version>`` image must be built.

Used by ``.github/workflows/release-publish.yml`` before each candidate build so a
re-run (e.g. a later ``targets=docker`` run after an HA-only release) reuses the
images already on GHCR instead of rebuilding and overwriting them.

  python -m scripts.release_image_gate --image ghcr.io/jochentcc/earnie-energy:2.7.0 \\
      --revision "$(git rev-parse HEAD)"

Prints ``exists=true|false`` (and appends it to ``$GITHUB_OUTPUT`` when set).

* image missing                          → ``exists=false`` (build it)
* image present, revision label matches  → ``exists=true``  (skip build)
* image present, revision label differs  → exit 1 (tag points at another commit —
  a rewritten tag must not silently ship the old image)
* image present without revision label   → ``exists=true`` with a ``::warning::``
  (built before the label was introduced; cannot be verified)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

REVISION_LABEL = "org.opencontainers.image.revision"


class RevisionMismatchError(RuntimeError):
    """The existing image was built from a different commit than the tag."""


def _inspect(image: str) -> dict[str, Any] | None:
    """Return the ``.Image`` config JSON of *image*, or ``None`` if it does not exist."""
    proc = subprocess.run(  # NOSONAR pythonsecurity:S8705
        ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Image}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if "not found" in proc.stderr.lower() or "manifest unknown" in proc.stderr.lower():
            return None
        raise RuntimeError(f"imagetools inspect {image} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def revisions(image_json: dict[str, Any]) -> set[str | None]:
    """Revision labels of a single-platform (``config``) or multi-arch (per-platform map) image."""
    if "config" in image_json:
        configs = [image_json]
    else:
        configs = list(image_json.values())
    return {(c.get("config") or {}).get("Labels", {}).get(REVISION_LABEL) for c in configs}


def decide(image: str, revision: str, image_json: dict[str, Any] | None) -> bool:
    """True if *image* already exists for *revision* (skip build)."""
    if image_json is None:
        return False
    found = revisions(image_json)
    if found == {None}:
        print(
            f"::warning::{image} exists without {REVISION_LABEL} label — "
            "reusing it unverified (built before idempotent releases)."
        )
        return True
    if found != {revision}:
        raise RevisionMismatchError(
            f"{image} exists but was built from {sorted(r or '?' for r in found)}, "
            f"tag is at {revision}. Delete that image version on GHCR or bump the version."
        )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True, help="Full image ref incl. :<version>")
    parser.add_argument("--revision", required=True, help="Git commit SHA of the release tag")
    args = parser.parse_args(argv)
    try:
        exists = decide(args.image, args.revision, _inspect(args.image))
    except (RevisionMismatchError, RuntimeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    line = f"exists={'true' if exists else 'false'}"
    print(f"{args.image}: {line}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
