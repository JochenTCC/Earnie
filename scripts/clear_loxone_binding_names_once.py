"""One-shot: clear Merker names from Loxone ehal_bindings (keep keys, Q8).

Usage:
  python -m scripts.clear_loxone_binding_names_once --config-dir <earnie_env/config> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from house_config.clear_loxone_binding_names import (
    clear_loxone_binding_names_in_components,
    clear_loxone_binding_names_in_house,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    house_path = args.config_dir / "house_profiles.json"
    components_path = args.config_dir / "components.json"
    if not house_path.is_file():
        print(f"missing {house_path}", file=sys.stderr)
        return 1
    house = json.loads(house_path.read_text(encoding="utf-8"))
    cleared_house = clear_loxone_binding_names_in_house(house)
    if not args.dry_run:
        house_path.write_text(
            json.dumps(cleared_house, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"{'dry-run ' if args.dry_run else ''}house_profiles.json cleared")
    if components_path.is_file():
        components = json.loads(components_path.read_text(encoding="utf-8"))
        cleared_c = clear_loxone_binding_names_in_components(components)
        if not args.dry_run:
            components_path.write_text(
                json.dumps(cleared_c, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(f"{'dry-run ' if args.dry_run else ''}components.json cleared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
