"""CLI: python -m tools.ha_loxone_bridge --mapping <file.json> --out-dir <dir>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checklist import render_checklist
from .ha_yaml import render_package
from .loxone_xml import outgoing_points, render_virtual_out, write_template
from .mapping import MappingError, load_mapping

PACKAGE_FILE = "ha_loxone_bridge.yaml"
XML_FILE = "VO_HA_Bridge.xml"
CHECKLIST_FILE = "Checkliste.md"


def generate(mapping_path: Path, out_dir: Path, *, allow_placeholder: bool = False) -> list[Path]:
    mapping = load_mapping(mapping_path, allow_placeholder=allow_placeholder)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    package = out_dir / PACKAGE_FILE
    package.write_text(render_package(mapping), encoding="utf-8", newline="\n")
    written.append(package)

    xml_name = None
    if outgoing_points(mapping):
        xml_name = XML_FILE
        xml_path = out_dir / XML_FILE
        write_template(xml_path, render_virtual_out(mapping))
        written.append(xml_path)

    checklist = out_dir / CHECKLIST_FILE
    checklist.write_text(
        render_checklist(mapping, package_file=PACKAGE_FILE, xml_file=xml_name), encoding="utf-8", newline="\n"
    )
    written.append(checklist)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="output directory; the XML contains webhook ids (secrets) — keep it out of git")
    parser.add_argument("--allow-placeholder", action="store_true",
                        help=f"accept webhook ids containing CHANGE_ME (dry run only)")
    args = parser.parse_args(argv)
    try:
        written = generate(args.mapping, args.out_dir, allow_placeholder=args.allow_placeholder)
    except MappingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
