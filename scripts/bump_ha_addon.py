#!/usr/bin/env python3
"""
bump_ha_addon.py — Pin HA add-on wrapper files to an Earnie release version.

Updates packaging/homeassistant-addon/earnie/ (build.yaml, config.yaml,
Dockerfile, CHANGELOG.md) so add-on SemVer mirrors the app version.

Usage:
  python -m scripts.bump_ha_addon --version 2.5.0-alpha.9
  python -m scripts.bump_ha_addon --version 2.5.0 --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = REPO_ROOT / "packaging" / "homeassistant-addon" / "earnie"
IMAGE_BASE = "ghcr.io/jochentcc/earnie-energy"
RELEASE_NOTES_DIR = REPO_ROOT / ".github" / "release-notes"
EARNIE_RELEASE_URL = "https://github.com/JochenTCC/Earnie/releases/tag/v{version}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def image_ref(version: str) -> str:
    return f"{IMAGE_BASE}:{version}"


def bump_build_yaml(content: str, version: str) -> str:
    ref = image_ref(version)
    content = re.sub(
        r"(^  aarch64: )ghcr\.io/jochentcc/earnie-energy:[^\n]+",
        rf"\g<1>{ref}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r"(^  amd64: )ghcr\.io/jochentcc/earnie-energy:[^\n]+",
        rf"\g<1>{ref}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r'(^  EARNIE_VERSION: )"[^"]+"',
        rf'\g<1>"{version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    return content


def bump_config_yaml(content: str, version: str) -> str:
    return re.sub(
        r'^version: "[^"]+"',
        f'version: "{version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )


def bump_dockerfile(content: str, version: str) -> str:
    return re.sub(
        r"^ARG EARNIE_VERSION=[^\n]+",
        f"ARG EARNIE_VERSION={version}",
        content,
        count=1,
        flags=re.MULTILINE,
    )


def _release_notes_blurb(version: str) -> str:
    notes_path = RELEASE_NOTES_DIR / f"v{version}.md"
    if notes_path.is_file():
        lines = _read(notes_path).splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
    return f"Pins Earnie `{version}` (`{image_ref(version)}`)."


def changelog_has_version(content: str, version: str) -> bool:
    return re.search(rf"^## {re.escape(version)}\s*$", content, flags=re.MULTILINE) is not None


def bump_changelog(content: str, version: str) -> str:
    if changelog_has_version(content, version):
        return content
    blurb = _release_notes_blurb(version)
    release_url = EARNIE_RELEASE_URL.format(version=version)
    section = (
        f"## {version}\n\n"
        f"- {blurb}\n"
        f"- Earnie release: [{version}]({release_url})\n\n"
    )
    lines = content.splitlines(keepends=True)
    insert_at = 0
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            insert_at = idx
            break
    else:
        insert_at = len(lines)
    return "".join(lines[:insert_at]) + section + "".join(lines[insert_at:])


def bump_addon_files(version: str, *, addon_dir: Path = ADDON_DIR) -> dict[Path, tuple[str, str]]:
    """Return mapping file path -> (before, after) for files that would change."""
    updates: dict[Path, tuple[str, str]] = {}
    spec = {
        "build.yaml": bump_build_yaml,
        "config.yaml": bump_config_yaml,
        "Dockerfile": bump_dockerfile,
    }
    for name, fn in spec.items():
        path = addon_dir / name
        before = _read(path)
        after = fn(before, version)
        if after != before:
            updates[path] = (before, after)

    changelog_path = addon_dir / "CHANGELOG.md"
    before = _read(changelog_path)
    after = bump_changelog(before, version)
    if after != before:
        updates[changelog_path] = (before, after)

    return updates


def apply_bump(version: str, *, addon_dir: Path = ADDON_DIR, dry_run: bool = False) -> bool:
    """Apply bump; return True if any file changed."""
    changes = bump_addon_files(version, addon_dir=addon_dir)
    if not changes:
        print(f"HA add-on already pinned to {version}; no changes.")
        return False

    for path, (_, after) in changes.items():
        label = path.name if path.parent == addon_dir else str(path)
        if dry_run:
            print(f"[dry-run] would update {label}")
        else:
            _write(path, after)
            print(f"Updated {label}")

    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pin HA add-on files to an Earnie release.")
    parser.add_argument(
        "--version",
        required=True,
        help="Earnie release version (matches version.py / GHCR tag, without leading v).",
    )
    parser.add_argument(
        "--addon-dir",
        type=Path,
        default=ADDON_DIR,
        help="Path to packaging/homeassistant-addon/earnie (for tests).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print files that would change without writing.",
    )
    args = parser.parse_args(argv)

    if not args.addon_dir.is_dir():
        print(f"Add-on directory not found: {args.addon_dir}", file=sys.stderr)
        return 1

    changed = apply_bump(args.version, addon_dir=args.addon_dir, dry_run=args.dry_run)
    return 0 if changed or args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
