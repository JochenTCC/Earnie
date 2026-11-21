"""Copy a pushed image from the personal GHCR namespace to the organisation namespace.

GitHub organisation move, Step 1: release images are published under
``ghcr.io/jochentcc/...`` (what installed systems pull) and also under
``ghcr.io/earnie-hems/...``. The copy is a registry-side manifest copy
(``docker buildx imagetools create``), no rebuild, so both names carry the same
digest. It is idempotent, so it also covers a re-run whose build step was skipped
because the image already existed (``scripts/release_image_gate.py``).

  python -m scripts.ghcr_mirror --image ghcr.io/jochentcc/earnie-addon-amd64:2.8.0

Fails loud when the organisation namespace cannot be written (token, org setup):
there is no fallback that skips the organisation copy.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from scripts.build_container import GHCR_NAMESPACE, ORG_GHCR_NAMESPACE


def org_image_ref(image: str) -> str:
    """Organisation-namespace ref for *image* (``ghcr.io/jochentcc/<name>:<tag>``)."""
    prefix = f"{GHCR_NAMESPACE}/"
    if not image.startswith(prefix):
        raise ValueError(f"{image!r} is not in the namespace {GHCR_NAMESPACE}")
    name = image[len(prefix):]
    if not name or ":" not in name.rsplit("/", 1)[-1]:
        raise ValueError(f"{image!r} has no tag (expected <name>:<tag>)")
    return f"{ORG_GHCR_NAMESPACE}/{name}"


def mirror_command(image: str) -> list[str]:
    """``imagetools create`` that points the organisation ref at *image*."""
    return ["docker", "buildx", "imagetools", "create", "-t", org_image_ref(image), image]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--image",
        action="append",
        required=True,
        metavar="IMAGE:TAG",
        help=f"Pushed image under {GHCR_NAMESPACE}/ (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        commands = [mirror_command(image) for image in args.image]
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for cmd in commands:
        print("+", " ".join(cmd))
        proc = subprocess.run(cmd, check=False)  # NOSONAR pythonsecurity:S8705
        if proc.returncode != 0:
            print(
                f"::error::Copy to {cmd[5]} failed. The workflow token needs write access to "
                f"the {ORG_GHCR_NAMESPACE} packages (see backlog: GitHub organisation move — Step 1).",
                file=sys.stderr,
            )
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
