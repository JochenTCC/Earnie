"""Build the HA testbed inputs from an Earnie configuration pack (HA Testbed P2).

Writes into an HA config directory:

* ``packages/earnie_ha_carrier.yaml`` — carrier YAML, every ``ENTITY_*`` filled
* ``earnie_house_sim/archetypes/<name>/`` — generated HouseSim archetype
* ``earnie_testbed_configuration.snippet.yaml`` — ``packages`` include for ``configuration.yaml``

``configuration.yaml`` itself is never touched (P3 patches it idempotently).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from house_sim.archetype_gen import (
    DEFAULT_INITIAL_SOC_PCT,
    DEFAULT_PV_POINTS,
    generate_archetype,
    load_pack,
    write_archetype,
)
from house_sim.contract import fill_yaml_placeholders
from house_sim.core.archetype import FIXTURES_DIR, list_archetypes
from integrations.ha_carrier_yaml import build_carrier_yaml
from scripts.house_sim_archetype_gen import _parse_static
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER

CARRIER_RELPATH = Path("packages") / "earnie_ha_carrier.yaml"
ARCHETYPES_RELPATH = Path("earnie_house_sim") / "archetypes"
SNIPPET_NAME = "earnie_testbed_configuration.snippet.yaml"
DEFAULT_ARCHETYPE_NAME = "earnie_pack"
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LEFTOVER_RE = re.compile(r"ENTITY_\w+")

SNIPPET = """\
# Add to the HA configuration.yaml (once):
homeassistant:
  packages: !include_dir_named packages
"""


def build_testbed(
    house: dict[str, Any],
    components: dict[str, Any],
    *,
    out_dir: Path,
    earnie_host: str,
    earnie_port: int,
    token: str,
    name: str = DEFAULT_ARCHETYPE_NAME,
    repeat_s: float | None = None,
    **archetype_kwargs: Any,
) -> list[Path]:
    """Generate archetype + filled carrier YAML; returns the written paths."""
    if not _NAME_RE.match(name):
        raise ValueError(f"archetype name {name!r} must match {_NAME_RE.pattern}")
    if name in list_archetypes(FIXTURES_DIR):
        raise ValueError(f"archetype name {name!r} is a shipped archetype; choose another --name")
    if not str(token or "").strip() or token == TOKEN_PLACEHOLDER:
        raise ValueError("a real push token is required (--token)")

    archetype = generate_archetype(house, components, **archetype_kwargs)
    raw = build_carrier_yaml(
        house,
        components,
        earnie_host=earnie_host,
        earnie_port=earnie_port,
        token=token,
        repeat_s=repeat_s,
    )
    filled = fill_yaml_placeholders(raw, archetype.placeholders)
    leftover = sorted(set(_LEFTOVER_RE.findall(filled)))
    if leftover:
        raise ValueError(f"unfilled placeholders in the carrier YAML: {', '.join(leftover)}")
    header = (
        f"# Filled by scripts.ha_testbed_build for archetype {name!r} "
        f"(pack sha256 {archetype.meta['source_pack_sha256'][:12]}).\n"
    )

    carrier = out_dir / CARRIER_RELPATH
    carrier.parent.mkdir(parents=True, exist_ok=True)
    carrier.write_text(header + filled, encoding="utf-8")
    written = [carrier]
    written += write_archetype(archetype, out_dir / ARCHETYPES_RELPATH / name)
    snippet = out_dir / SNIPPET_NAME
    snippet.write_text(SNIPPET, encoding="utf-8")
    written.append(snippet)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HA testbed inputs from an Earnie pack (HA Testbed P2)")
    parser.add_argument("--config-dir", type=Path, required=True, help="Earnie config dir (pack)")
    parser.add_argument("--out", type=Path, required=True, help="HA config dir (e.g. ha_lab/homeassistant)")
    parser.add_argument("--earnie-host", required=True, help="Earnie listener host as seen from HA")
    parser.add_argument("--earnie-port", type=int, default=8541)
    parser.add_argument("--token", required=True, help="push token (EARNIE_PILOT_PUSH_TOKEN)")
    parser.add_argument("--repeat-s", type=float, default=None)
    parser.add_argument("--name", default=DEFAULT_ARCHETYPE_NAME, help="archetype name in HA")
    parser.add_argument("--battery-kwh", type=float)
    parser.add_argument("--load-kw", type=float)
    parser.add_argument("--initial-soc", type=float, default=DEFAULT_INITIAL_SOC_PCT)
    parser.add_argument("--pv-points", type=int, default=DEFAULT_PV_POINTS)
    parser.add_argument("--static", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args(argv)
    try:
        house, components = load_pack(args.config_dir)
        written = build_testbed(
            house,
            components,
            out_dir=args.out,
            earnie_host=args.earnie_host,
            earnie_port=args.earnie_port,
            token=args.token,
            name=args.name,
            repeat_s=args.repeat_s,
            battery_kwh=args.battery_kwh,
            load_kw=args.load_kw,
            initial_soc_pct=args.initial_soc,
            static_overrides=_parse_static(args.static),
            pv_points=args.pv_points,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
