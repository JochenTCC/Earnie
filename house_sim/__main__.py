"""CLI: start mock HA REST and optionally run closed-loop ticks."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time

from house_sim.archetype import load_archetype
from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest
from house_sim.stepper import run_ticks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m house_sim",
        description="HA Lab P1 developer bench: mock Home Assistant REST + short physics ticks.",
    )
    parser.add_argument(
        "--fixture",
        default="evcc_en",
        help="Archetype name under house_sim/fixtures/ (default: evcc_en)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--token", default=DEFAULT_BENCH_TOKEN)
    parser.add_argument(
        "--ticks",
        type=int,
        default=0,
        help="If >0, run this many closed-loop ticks then exit (no long-lived server).",
    )
    parser.add_argument(
        "--dt-h",
        type=float,
        default=0.25,
        help="Tick duration in hours (default: 0.25 = 15 min).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    package = load_archetype(args.fixture)
    store = package.build_store()

    if args.ticks > 0:
        state = run_ticks(package, store, n_ticks=args.ticks, dt_h=args.dt_h)
        print(json.dumps(state.as_dict(), indent=2))
        return 0

    server, base_url = start_mock_rest(
        store, host=args.host, port=args.port, token=args.token
    )
    print("house_sim mock HA listening")
    print(f"  base_url: {base_url}")
    print(f"  token:    {args.token}")
    print(f"  fixture:  {package.root}")
    print("  ehal.ha.entities:")
    print(json.dumps(package.ehal_entities, indent=2))
    if package.ehal_sign:
        print("  ehal.ha.sign:")
        print(json.dumps(package.ehal_sign, indent=2))
    print("Ctrl+C to stop.")

    def _stop(_signum=None, _frame=None) -> None:
        stop_mock_rest()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        while True:
            time.sleep(1.0)
    finally:
        stop_mock_rest()
        del server
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
