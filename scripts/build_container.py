#!/usr/bin/env python3
"""
build_container.py – Kanonischer Docker-Build für Synology (amd64) und LoxBerry (arm64).

Aufruf:
  python -m scripts.build_container
  python -m scripts.build_container --target all --push
  .\\docker\\build-container.ps1 --target synology --push
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from version import __version__

DEFAULT_REGISTRY_IMAGE = "ghcr.io/jochentcc/earnie-energy"
LEGACY_REGISTRY_IMAGE = "ghcr.io/jochentcc/ernie-energy"
DEFAULT_PLATFORM = "linux/amd64"
MULTIARCH_PLATFORM = "linux/amd64,linux/arm64"
TARGET_PLATFORMS = {
    "synology": "linux/amd64",
    "loxberry": "linux/arm64",
    "all": MULTIARCH_PLATFORM,
}
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_deploy_tariff_gate() -> None:
    """Deploy-Gate: gebündelter Tarifkatalog muss plausibel und vollständig sein."""
    from scripts.validate_tariffs import run_validation

    share_config = REPO_ROOT / "share" / "config"
    tariffs_path = str(share_config / "tariffs.json")
    errors = run_validation(
        tariffs_path=tariffs_path,
        scenarios_path=str(share_config / "backtesting_scenarios.example.json"),
        schema_path=str(share_config / "tariffs.schema.json"),
        check_catalog=True,
        import_json=str(REPO_ROOT / "docs" / "spec" / "stromtarife_dach_kombiniert.json"),
        export_json=str(REPO_ROOT / "docs" / "spec" / "einspeisetarife_dach_erweitert.json"),
    )
    if errors:
        detail = "\n".join(f"  - {item}" for item in errors)
        raise ValueError(
            "Deploy-Gate: Tarif-Plausibilität fehlgeschlagen "
            f"({tariffs_path}):\n{detail}"
        )
    print("Deploy-Gate: Tarifkatalog OK.")


def is_prerelease_version(version: str) -> bool:
    """True for SemVer pre-releases (e.g. 2.2.0-alpha.1, 2.2.0-rc.1)."""
    return "-" in version


def default_tags(version: str | None = None) -> list[str]:
    """Default GHCR tags for *version* (defaults to ``version.__version__``).

    Official releases get ``:latest`` and ``:<version>`` (plus legacy aliases).
    Pre-releases get only ``:<version>`` so ``:latest`` stays on the last official build.
    """
    ver = __version__ if version is None else version
    include_latest = not is_prerelease_version(ver)
    tags: list[str] = []
    for image in (DEFAULT_REGISTRY_IMAGE, LEGACY_REGISTRY_IMAGE):
        if include_latest:
            tags.append(f"{image}:latest")
        tags.append(f"{image}:{ver}")
    return tags


def is_multiarch(platform: str) -> bool:
    return "," in platform


def resolve_platform(target: str | None, platform: str | None) -> str:
    if target and platform:
        raise ValueError("Nur --target oder --platform angeben, nicht beides.")
    if target:
        if target not in TARGET_PLATFORMS:
            valid = ", ".join(sorted(TARGET_PLATFORMS))
            raise ValueError(f"Unbekanntes --target {target!r}; erlaubt: {valid}")
        return TARGET_PLATFORMS[target]
    return platform or DEFAULT_PLATFORM


def build_command(
    *,
    tags: list[str],
    platform: str,
    dockerfile: Path,
    context: Path,
    no_cache: bool,
    push: bool,
) -> list[str]:
    if not tags:
        raise ValueError("Mindestens ein Image-Tag ist erforderlich.")
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Dockerfile nicht gefunden: {dockerfile}")
    if not context.is_dir():
        raise FileNotFoundError(f"Build-Kontext nicht gefunden: {context}")
    if is_multiarch(platform) and not push:
        raise ValueError(
            "Multi-Arch-Build (--target all) erfordert --push. "
            "Für lokalen Test: --target synology oder --target loxberry."
        )

    if is_multiarch(platform):
        cmd = ["docker", "buildx", "build", "--platform", platform, "-f", str(dockerfile)]
        for tag in tags:
            cmd.extend(["-t", tag])
        if no_cache:
            cmd.append("--no-cache")
        cmd.append("--push")
        cmd.append(str(context))
        return cmd

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
        description=(
            "Docker-Image für Earnie bauen "
            "(Standard: Synology linux/amd64; Multi-Arch: --target all --push)."
        )
    )
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        metavar="IMAGE:TAG",
        help=(
            "Image-Tag (mehrfach). Ohne Angabe: "
            f"{DEFAULT_REGISTRY_IMAGE}:<version> und ggf. :latest "
            "(kein :latest bei SemVer-Pre-Releases in version.py)"
        ),
    )
    parser.add_argument(
        "--target",
        choices=sorted(TARGET_PLATFORMS),
        help="Deploy-Ziel: synology (amd64), loxberry (arm64), all (beide via buildx)",
    )
    parser.add_argument(
        "--platform",
        help=f"Zielplattform (Standard ohne --target: {DEFAULT_PLATFORM})",
    )
    parser.add_argument(
        "--dockerfile",
        type=Path,
        default=REPO_ROOT / "docker" / "Dockerfile",
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
        help="Image(s) nach Registry pushen (bei --target all implizit im buildx-Lauf)",
    )
    parser.add_argument("--no-cache", action="store_true", help="Docker-Build ohne Cache")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tags = args.tags or default_tags()
    try:
        if args.push:
            _run_deploy_tariff_gate()
        platform = resolve_platform(args.target, args.platform)
        cmd = build_command(
            tags=tags,
            platform=platform,
            dockerfile=args.dockerfile,
            context=args.context,
            no_cache=args.no_cache,
            push=args.push,
        )
        run_build(cmd)
        if args.push and not is_multiarch(platform):
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
