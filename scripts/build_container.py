#!/usr/bin/env python3
"""
build_container.py – Kanonischer Docker-Build für Synology/NAS (linux/amd64).

Aufruf:
  python -m scripts.build_container
  python -m scripts.build_container --push
  .\\build-container.ps1 --tag ghcr.io/jochentcc/ernie-energy:latest --push
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from version import __version__

DEFAULT_REGISTRY_IMAGE = "ghcr.io/jochentcc/ernie-energy"
DEFAULT_PLATFORM = "linux/amd64"
REPO_ROOT = Path(__file__).resolve().parents[1]


def default_tags() -> list[str]:
    return [f"{DEFAULT_REGISTRY_IMAGE}:latest", f"{DEFAULT_REGISTRY_IMAGE}:{__version__}"]


def build_command(
    *,
    tags: list[str],
    platform: str,
    dockerfile: Path,
    context: Path,
    no_cache: bool,
) -> list[str]:
    if not tags:
        raise ValueError("Mindestens ein Image-Tag ist erforderlich.")
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Dockerfile nicht gefunden: {dockerfile}")
    if not context.is_dir():
        raise FileNotFoundError(f"Build-Kontext nicht gefunden: {context}")

    cmd = ["docker", "build", "--platform", platform, "-f", str(dockerfile)]
    for tag in tags:
        cmd.extend(["-t", tag])
    if no_cache:
        cmd.append("--no-cache")
    cmd.append(str(context))
    return cmd


def run_build(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def run_push(tags: list[str]) -> None:
    for tag in tags:
        cmd = ["docker", "push", tag]
        print("+", " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Docker-Image für Energy Optimizer bauen (Standard: Synology linux/amd64)."
    )
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        metavar="IMAGE:TAG",
        help=f"Image-Tag (mehrfach). Ohne Angabe: {DEFAULT_REGISTRY_IMAGE}:latest und :{__version__}",
    )
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        help=f"Zielplattform (Standard: {DEFAULT_PLATFORM})",
    )
    parser.add_argument(
        "--dockerfile",
        type=Path,
        default=REPO_ROOT / "Dockerfile",
        help="Pfad zum Dockerfile",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=REPO_ROOT,
        help="Build-Kontext (Standard: Projektroot)",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Alle Tags nach erfolgreichem Build zu Registry pushen",
    )
    parser.add_argument("--no-cache", action="store_true", help="Docker-Build ohne Cache")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tags = args.tags or default_tags()
    try:
        cmd = build_command(
            tags=tags,
            platform=args.platform,
            dockerfile=args.dockerfile,
            context=args.context,
            no_cache=args.no_cache,
        )
        run_build(cmd)
        if args.push:
            run_push(tags)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1

    print(f"Fertig: {', '.join(tags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
