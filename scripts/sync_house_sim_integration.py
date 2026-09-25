"""Copy house_sim/core + fixtures into the HA custom integration tree.

Generated copy under custom_components/earnie_house_sim/_core/ and fixtures/
must never be hand-edited. Edit house_sim/core/ (and fixtures) then re-run:

  .venv\\Scripts\\python.exe -m scripts.sync_house_sim_integration
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_CORE = REPO_ROOT / "house_sim" / "core"
SRC_FIXTURES = REPO_ROOT / "house_sim" / "fixtures"
DEST_ROOT = (
    REPO_ROOT
    / "house_sim"
    / "ha_integration"
    / "custom_components"
    / "earnie_house_sim"
)
DEST_CORE = DEST_ROOT / "_core"
DEST_FIXTURES = DEST_ROOT / "fixtures"
CHECKSUM_NAME = "_sync_checksums.json"

GENERATED_HEADER = (
    "# GENERATED — edit house_sim/core/ (or fixtures), then run:\n"
    "#   python -m scripts.sync_house_sim_integration\n"
    "# Do not hand-edit this copy.\n"
)


def _rel_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "__pycache__" or path.suffix == ".pyc":
            continue
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _copy_tree(src: Path, dest: Path, *, prepend_py_header: bool) -> dict[str, str]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}
    for src_file in _rel_files(src):
        rel = src_file.relative_to(src).as_posix()
        dest_file = dest / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        raw = src_file.read_bytes()
        if prepend_py_header and src_file.suffix == ".py":
            text = raw.decode("utf-8")
            if not text.startswith("# GENERATED"):
                text = GENERATED_HEADER + text
            dest_file.write_text(text, encoding="utf-8", newline="\n")
        else:
            dest_file.write_bytes(raw)
        checksums[rel] = _sha256(src_file)
    return checksums


def sync(*, dry_run: bool = False) -> dict[str, object]:
    if not SRC_CORE.is_dir():
        raise FileNotFoundError(f"Missing source core: {SRC_CORE}")
    if not SRC_FIXTURES.is_dir():
        raise FileNotFoundError(f"Missing source fixtures: {SRC_FIXTURES}")
    if dry_run:
        return {
            "core_files": [p.relative_to(SRC_CORE).as_posix() for p in _rel_files(SRC_CORE)],
            "fixture_files": [
                p.relative_to(SRC_FIXTURES).as_posix() for p in _rel_files(SRC_FIXTURES)
            ],
        }

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    core_sums = _copy_tree(SRC_CORE, DEST_CORE, prepend_py_header=True)
    fixture_sums = _copy_tree(SRC_FIXTURES, DEST_FIXTURES, prepend_py_header=False)
    payload = {
        "core": core_sums,
        "fixtures": fixture_sums,
    }
    (DEST_ROOT / CHECKSUM_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be copied without writing.",
    )
    args = parser.parse_args(argv)
    payload = sync(dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
    else:
        core_n = len(payload["core"])  # type: ignore[arg-type]
        fix_n = len(payload["fixtures"])  # type: ignore[arg-type]
        print(f"Synced {core_n} core files and {fix_n} fixture files → {DEST_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
