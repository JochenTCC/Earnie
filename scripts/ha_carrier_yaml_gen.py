"""Generate HA push carrier YAML package from house_profiles + components bindings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from integrations.ha_carrier_yaml import DEFAULT_WATCHDOG_TIMEOUT_S, build_carrier_yaml
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HA push carrier YAML package (Binding P5c)"
    )
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--host", required=True, help="Earnie listener host (IP or Docker DNS)")
    parser.add_argument("--port", type=int, default=8541)
    parser.add_argument("--out", type=Path, help="Write YAML here; default stdout")
    parser.add_argument(
        "--token",
        default=TOKEN_PLACEHOLDER,
        help="Push token (default placeholder — set EARNIE_PUSH_TOKEN in lab)",
    )
    parser.add_argument(
        "--repeat-s",
        type=float,
        default=None,
        help="Push time_pattern interval seconds (default: EARNIE_PUSH_REPEAT_S or 10)",
    )
    parser.add_argument(
        "--watchdog-s",
        type=float,
        default=DEFAULT_WATCHDOG_TIMEOUT_S,
        help="Release a forced ESS active power when status.json is unreachable this "
        f"long (default {DEFAULT_WATCHDOG_TIMEOUT_S:g}; 0 = no watchdog)",
    )
    args = parser.parse_args(argv)
    config_dir = args.config_dir
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    text = build_carrier_yaml(
        house,
        components,
        earnie_host=args.host,
        earnie_port=args.port,
        token=args.token,
        repeat_s=args.repeat_s,
        watchdog_s=args.watchdog_s,
    )
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
