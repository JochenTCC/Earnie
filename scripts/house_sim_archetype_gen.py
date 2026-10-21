"""Generate a HouseSim archetype directory from an Earnie configuration pack (HA Testbed P1)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from house_sim.archetype_gen import (
    DEFAULT_INITIAL_SOC_PCT,
    DEFAULT_PV_POINTS,
    generate_archetype,
    load_pack,
    write_archetype,
)


def _parse_static(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--static expects KEY=VALUE, got {item!r}")
        out[key.strip()] = value.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HouseSim archetype from house_profiles.json + components.json (HA Testbed P1)"
    )
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="archetype directory to write")
    parser.add_argument("--battery-kwh", type=float, help="battery capacity (default: components.json)")
    parser.add_argument("--load-kw", type=float, help="base load (default: profile annual_kwh / 8760)")
    parser.add_argument("--initial-soc", type=float, default=DEFAULT_INITIAL_SOC_PCT)
    parser.add_argument("--pv-points", type=int, default=DEFAULT_PV_POINTS)
    parser.add_argument(
        "--static",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="static value for a non-physical read, KEY = qualified EHAL id or field kind",
    )
    args = parser.parse_args(argv)
    try:
        house, components = load_pack(args.config_dir)
        archetype = generate_archetype(
            house,
            components,
            battery_kwh=args.battery_kwh,
            load_kw=args.load_kw,
            initial_soc_pct=args.initial_soc,
            static_overrides=_parse_static(args.static),
            pv_points=args.pv_points,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    written = write_archetype(archetype, args.out)
    meta = archetype.meta
    print(
        f"{len(archetype.placeholders)} signals "
        f"({len(meta['physical'])} physical, {len(meta['static_signals'])} static) -> {args.out}"
    )
    for path in written:
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
